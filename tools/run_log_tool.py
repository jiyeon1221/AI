#!/usr/bin/env python3
"""Run Log Tool — Google Spreadsheet에 실험 로그 기록"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from typing import Dict, Any
from pathlib import Path

from .base_tool import BaseTool
from .config_loader import (
    get_last_finished_run_number,
    get_path_config,
    get_run_log_beam_type,
    get_run_log_fixed_hv_path,
)
from .hv_control_tool import HVControlTool
from .hodoscope_hv_tool import read_hv_from_log

# YAML 기반 실행 로그 설정.
JSON_KEY_FILE = get_path_config("JsonKeyFile")
SPREADSHEET_ID = get_path_config("SpreadsheetId")

class RunLogTool(BaseTool):
    """Google Spreadsheet에 실험 로그를 기록하는 Tool"""
    
    def __init__(self):
        super().__init__(
            name="run_log_tool",
            description="Record experimental logs to Google Spreadsheet"
        )
        self.client = None
        self.sheet = None

    def _authenticate(self):
        """Google Sheets API 인증 및 시트 연결"""
        if self.sheet:
            return True
            
        try:
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]
            creds = Credentials.from_service_account_file(str(JSON_KEY_FILE), scopes=scopes)
            self.client = gspread.authorize(creds)
            # 스프레드시트 ID로 문서를 연다.
            spreadsheet = self.client.open_by_key(SPREADSHEET_ID)
            # 첫 번째 워크시트에 기록한다.
            self.sheet = spreadsheet.get_worksheet(0)
            return True
        except Exception as e:
            print(f"❌ Google Spreadsheet 인증 실패: {str(e)}")
            return False

    def execute(self, params: Dict[str, Any]) -> str:
        """
        Args:
            params:
                - command (str): "write" | "update" | "read"
                - run_num, program, notes, evts, start_time, end_time, config
        """
        if not self._authenticate():
            raise RuntimeError("Google Spreadsheet 인증에 실패했습니다.")

        command = params.get("command", "write")

        if command == "write":
            return self._write_row(params)
        elif command == "update":
            return self._update_row(params)
        elif command == "read":
            return self._read_row(params)
        else:
            raise RuntimeError(f"지원하지 않는 명령입니다: {command}")

    @staticmethod
    def _parse_fixed_hv(path: Path) -> Dict[str, str]:
        """기준 HV 파일 파싱 → {CHANNEL: vset} dict"""
        result = {}
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if ":" in line:
                    ch, val = line.split(":", 1)
                    result[ch.strip().upper()] = val.strip()
        return result

    def _build_hv_drc_string(self, name_to_vset: Dict[str, str]) -> str:
        """비교 기준 HV 파일(RunLog.FixedHvFile) 유무에 따라 DRC HV 문자열 생성.

        비교 기준은 실험 시기마다 달라질 수 있어 config에서 지정한다 — 여기서는 읽기만
        하고, fixed_hv.txt 갱신은 hv_equalization_tool.write_fixed_hv가 담당한다."""
        # 타워와 MCP의 S/C 채널을 쌍으로 묶는다.
        groups = [(f"T{i}S", f"T{i}C") for i in range(1, 10)] + [("MCP-S", "MCP-C")]

        fixed_hv_path = get_run_log_fixed_hv_path()
        if fixed_hv_path.exists():
            fixed = self._parse_fixed_hv(fixed_hv_path)
            diff_lines = []
            for pair in groups:
                parts = []
                for name in pair:
                    cur = name_to_vset.get(name, "")
                    if cur and cur != fixed.get(name, ""):
                        parts.append(f"{name}:{cur}")
                if parts:
                    diff_lines.append(" ".join(parts))
            if not diff_lines:
                return "Same as Fixed HV"
            return "Compared to Fixed HV\n" + "\n".join(diff_lines)
        else:
            lines = []
            for pair in groups:
                parts = [
                    f"{name}:{name_to_vset[name]}"
                    for name in pair
                    if name_to_vset.get(name, "") != ""
                ]
                if parts:
                    lines.append(" ".join(parts))
            return "\n".join(lines)

    def _collect_hv_vset_snapshot(self) -> Dict[str, str]:
        """
        HV config에서 채널별 V0Set snapshot 수집.
        - Aux: Trig1, Trig2
        - DRC: 비교 기준 HV 파일(RunLog.FixedHvFile) 존재 시 비교, 없으면 전체 출력
        """
        hv = HVControlTool()
        try:
            if not hv._ensure_connection():
                return {"hv_drc": "", "hv_aux": ""}

            rows = hv._read_config_rows()
            name_to_vset = {}
            for row in rows:
                name = str(row.get("name", "")).strip()
                if not name or name.lower() == "none":
                    continue
                name_to_vset[name.upper()] = str(row.get("V0Set", "")).strip()

            aux_names = ["TRIG1", "TRIG2"]
            hv_aux = "\n".join(
                f"{name}:{name_to_vset[name]}"
                for name in aux_names
                if name in name_to_vset and name_to_vset[name] != ""
            )
            hv_drc = self._build_hv_drc_string(name_to_vset)
            return {"hv_drc": hv_drc, "hv_aux": hv_aux}
        except Exception:
            return {"hv_drc": "", "hv_aux": ""}
        finally:
            try:
                if hv.ssh_client:
                    hv.ssh_client.close()
            except Exception:
                pass

    def _write_row(self, params: Dict[str, Any]) -> str:
        """새로운 로그 행 추가 (DAQ 호출용)"""
        run_num = params.get("run_num")
        if not run_num:
            last = get_last_finished_run_number()
            run_num = str(last) if last is not None else "Unknown"

        program = params.get("program", "")
        evts = params.get("evts", "")
        start_time = params.get("start_time", "")
        end_time = params.get("end_time", "")
        config = params.get("config", "")
        notes = params.get("notes", "")
        
        def safe_round(val, digits=1):
            if val == "" or val is None:
                return ""
            try:
                return round(float(val), digits)
            except (ValueError, TypeError):
                return val

        pos_h = safe_round(params.get("pos_h", ""))
        pos_v = safe_round(params.get("pos_v", ""))
        pos_rot = safe_round(params.get("pos_rot", ""))
        pos_tilt = safe_round(params.get("pos_tilt", ""))
        beam_energy = params.get("beam_energy", "")

        # 요청값이 없으면 설정의 빔 유형을 사용한다.
        beam_type = params.get("beam_type") or get_run_log_beam_type()

        hv_drc = params.get("hv_drc", "")
        hv_aux = params.get("hv_aux", "")
        if hv_drc == "" and hv_aux == "":
            hv_snapshot = self._collect_hv_vset_snapshot()
            hv_drc = hv_snapshot.get("hv_drc", "")
            hv_aux = hv_snapshot.get("hv_aux", "")

        # 실행 로그의 호도스코프 채널별 HV를 추가한다.
        hodo_hvs = read_hv_from_log(str(run_num))
        if hodo_hvs:
            hodo_str = "\n".join(
                f"Hodo[{ch}]:{hodo_hvs[ch]}" for ch in sorted(hodo_hvs)
            )
            hv_aux = f"{hv_aux}\n{hodo_str}" if hv_aux else hodo_str

        # 실행 시간과 초당 이벤트 수를 계산한다.
        duration_secs = ""
        rate = ""
        if start_time and end_time:
            try:
                dt_fmt = "%Y-%m-%d %H:%M:%S"
                dt_start = datetime.strptime(start_time, dt_fmt)
                dt_end   = datetime.strptime(end_time,   dt_fmt)
                duration_secs = int((dt_end - dt_start).total_seconds())
                if evts and duration_secs > 0:
                    rate = round(int(evts) / duration_secs, 1)
            except (ValueError, TypeError):
                pass

        # 자동화 대상 열만 기록한다. Trigger Setup은 수동 입력 열이다.
        # B(2): Program | C(3): Run # | D(4): evts | E(5): start | F(6): end | G(7): Duration
        # H(8): HV DRC | I(9): HV Aux | J(10): Pos H | K(11): Pos V | L(12): Pos Rot | M(13): Pos Tilt
        # O(15): Beam Type | P(16): Beam Energy | Q(17): Rate | R(18): Config | S(19): Notes
        ai_columns = {
            'B': program,
            'C': run_num,
            'D': evts,
            'E': start_time,
            'F': end_time,
            'G': duration_secs,
            'H': hv_drc,
            'I': hv_aux,
            'J': pos_h,
            'K': pos_v,
            'L': pos_rot,
            'M': pos_tilt,
            'O': beam_type,
            'P': beam_energy,
            'Q': rate,
            'R': config,
            'S': notes,
        }

        try:
            # 실행 번호가 있는 마지막 데이터 행을 찾는다.
            col_c_values = self.sheet.col_values(3)
            next_row = len(col_c_values) + 1

            # 데이터는 헤더 다음인 6행부터 시작한다.
            if next_row < 6:
                next_row = 6

            batch_data = [
                {'range': f'{col}{next_row}', 'values': [[val]]}
                for col, val in ai_columns.items()
                if val != "" and val is not None
            ]
            if batch_data:
                self.sheet.batch_update(batch_data, value_input_option='USER_ENTERED')

            return f"✅ 새 Run 로그 추가 완료 (Run: {run_num}, Row: {next_row})"
        except Exception as e:
            raise RuntimeError(f"로그 추가 실패: {str(e)}") from e

    # 읽기용 1부터 시작하는 열 번호와 이름.
    _HEADER_ROW = 5
    _READ_COLUMNS = {
        2: "Program", 3: "Run #", 4: "Events", 5: "Start", 6: "End",
        7: "Duration", 8: "HV DRC", 9: "HV Aux", 10: "Pos H", 11: "Pos V",
        12: "Pos Rot", 13: "Pos Tilt", 14: "Trigger", 15: "Beam Type",
        16: "Beam Energy", 17: "Rate", 18: "Config", 19: "Notes",
    }

    def _read_row(self, params: Dict[str, Any]) -> str:
        """Run 번호로 해당 행의 모든 정보를 읽어 반환"""
        run_num = params.get("run_num")
        if not run_num:
            return "⚠️ 조회할 Run 번호를 알려주세요."
        try:
            all_data = self.sheet.get_all_values()
            target_row = None
            for row in all_data:
                if len(row) > 2 and str(row[2]) == str(run_num):
                    target_row = row
                    break
            if target_row is None:
                raise RuntimeError(f"Run {run_num}을 시트에서 찾을 수 없습니다.")

            lines = [f"📋 Run {run_num} 로그:"]
            for col_idx, label in sorted(self._READ_COLUMNS.items()):
                val = target_row[col_idx - 1] if col_idx - 1 < len(target_row) else ""
                if val:
                    lines.append(f"  {label}: {val}")
            return "\n".join(lines)
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"로그 조회 실패: {str(e)}") from e

    # 열 이름별 시트 열 번호와 표시명.
    UPDATABLE_COLUMNS = {
        "program":       (2,  "Program"),
        "evts":          (4,  "Events"),
        "end_time":      (6,  "End"),
        "duration":      (7,  "Duration"),
        "notes":         (19, "Notes"),
        "config":        (18, "Config"),
        "beam_energy":   (16, "Beam Energy"),
        "beam_type":     (15, "Beam Type"),
        "trigger_setup": (14, "Trigger Setup"),
        "rate":          (17, "Rate"),
        "hv_drc":        (8,  "HV DRC"),
        "hv_aux":        (9,  "HV Aux"),
    }

    def _update_row(self, params: Dict[str, Any]) -> str:
        """기존 로그 행 업데이트 (UPDATABLE_COLUMNS 에 있는 모든 열 지원)"""
        run_num = params.get("run_num")

        to_update = {
            col: params[col]
            for col in self.UPDATABLE_COLUMNS
            if params.get(col) is not None
        }

        if not to_update:
            return "⚠️ 업데이트할 정보가 없습니다."

        try:
            all_data = self.sheet.get_all_values()

            if run_num:
                target_row_idx = -1
                for i, row in enumerate(all_data):
                    if len(row) > 2 and str(row[2]) == str(run_num):
                        target_row_idx = i + 1
                        break
            else:
                target_row_idx = len(all_data)
                run_num = all_data[-1][2] if len(all_data[-1]) > 2 else "Last"

            if target_row_idx <= 1:
                raise RuntimeError(f"Run {run_num}을 시트에서 찾을 수 없습니다.")

            updates = []
            for col_key, value in to_update.items():
                col_idx, label = self.UPDATABLE_COLUMNS[col_key]
                self.sheet.update_cell(target_row_idx, col_idx, value)
                updates.append(f"{label}='{value}'")

            return f"✅ Run {run_num} 업데이트 완료: {', '.join(updates)}"

        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"로그 업데이트 실패: {str(e)}") from e
