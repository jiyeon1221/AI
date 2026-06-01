#!/usr/bin/env python3
"""
HV Control Tool — CAEN HV Supply 제어 (SSH 원격)

Available Commands:
- 'voltage': 전압 설정 (requires: channels, voltage)
- 'current': 전류 설정 (requires: channels, current)
- 'on': HV 전원 켜기 (requires: channels)
- 'off': HV 전원 끄기 (requires: channels)
- 'status': 상태 확인 (optional: channels, default='all')

Channel Specification:
- 'all' 또는 '전체': 모든 채널 (0-23)
- [0, 1, 2]: 특정 채널 리스트 (채널 번호)
- ['T1C', 'T2C']: Name으로 채널 지정
- [0, 'T1C', 'T2C']: 채널 번호와 Name 혼합 가능
- '0-5': 범위 지정
- '0,2,4': 쉼표로 구분
- 'T1C,T2C': Name으로 쉼표 구분
"""

import json
import re
import shlex
from typing import Dict, Any, List, Tuple
from datetime import datetime

import paramiko

from .base_tool import BaseTool
from .config_loader import get_hv_config


# ===== HV 설정 (Config from YAML) =====
_hv_config = get_hv_config()
_hv_ssh = _hv_config.get('SSH', {})
_hv_paths = _hv_config.get('Paths', {})

HV_SSH_CONFIG = {
    'host': _hv_ssh.get('Host'),
    'port': _hv_ssh.get('Port'),
    'username': _hv_ssh.get('Username'),
    'password': _hv_ssh.get('Password'),
    'key_path': _hv_ssh.get('KeyPath')
}

HV_WRAPPER_WORKDIR = _hv_paths.get('WrapperWorkDir')
HV_CONFIG_FILENAME = "config.txt"
HV_CONFIG_RELATIVE_PATH = f"../config/{HV_CONFIG_FILENAME}"
HV_CONFIG_FULL_PATH = _hv_paths.get('ConfigFullPath')
HV_ENV_PRE_COMMAND = "export LD_LIBRARY_PATH=/usr/lib64/:$LD_LIBRARY_PATH"


class HVControlTool(BaseTool):
    """HV 제어 Tool"""
    
    def __init__(self):
        super().__init__(
            name="hv_execute_tool",
            description=(
                "Control CAEN high voltage (HV) system. "
                "Available commands: "
                "1) 'voltage' - Set voltage (requires: channels, voltage), "
                "2) 'current' - Set current (requires: channels, current), "
                "3) 'on' - Turn on HV channels (requires: channels), "
                "4) 'off' - Turn off HV channels (requires: channels), "
                "5) 'status' - Check HV status (optional: channels). "
                "For channels parameter, use 'all' for all channels (0-23), "
                "channel numbers like [0,1,2], or channel names like ['T1C','T2C'], "
                "or mix them like [0,'T1C']. Case-insensitive for names. "
                "Aux channels (trigger PMTs) can be specified by name: ['TRIG1','TRIG2']."
            )
        )
        self.ssh_client = None
    
    def execute(self, params: Dict[str, Any]) -> str:
        """
        Args:
            params:
                - command (str): 'voltage' | 'current' | 'on' | 'off' | 'status'
                - channels (list or str, optional): 채널 지정 ('all', [0,1], ['T1C'], 범위 등)
                - channel_values (dict, optional): 채널별 다른 값 설정
                - voltage (float, optional): 전압 값 (V)
                - current (float, optional): 전류 값 (μA)
        """
        valid, error = self.validate_params(params, ["command"])
        if not valid:
            raise RuntimeError(f"파라미터 오류: {error}")

        command = params["command"].lower()

        try:
            if not self._ensure_connection():
                raise RuntimeError(
                    f"SSH Connection Failed — "
                    f"{HV_SSH_CONFIG['host']}:{HV_SSH_CONFIG['port']} "
                    f"에 연결할 수 없습니다. HV 서버가 실행 중인지 확인하세요."
                )

            if command == "voltage":
                return self._set_voltage(params)
            elif command == "current":
                return self._set_current(params)
            elif command == "on":
                return self._power_toggle(params, "On")
            elif command == "off":
                return self._power_toggle(params, "Off")
            elif command == "status":
                return self._get_status(params)
            else:
                raise RuntimeError(
                    f"Unsupported command: {command}. "
                    f"Supported: voltage, current, on, off, status"
                )

        except RuntimeError:
            raise
        except Exception as e:
            import traceback
            raise RuntimeError(
                f"HV Control Error: {str(e)}\n{traceback.format_exc()}"
            ) from e
        
        finally:
            # SSH 연결 유지 (재사용을 위해)
            pass
    
    def _set_voltage(self, params: Dict[str, Any]) -> str:
        """전압 설정"""
        if "channel_values" in params:
            channel_values = params["channel_values"]
            if not channel_values:
                return "❌ channel_values가 비어있습니다"
            
            rows = self._read_config_rows()
            row_map = {row['ch']: row for row in rows}
            try:
                name_to_ch_map = self._get_name_to_channel_map(rows)
            except ValueError as e:
                return str(e)
            
            resolved_channels = []
            for identifier, voltage in channel_values.items():
                ch_list = self._resolve_single_identifier(str(identifier), name_to_ch_map)
                if not ch_list:
                    return f"❌ '{identifier}'에 해당하는 채널을 찾을 수 없습니다"
                
                for ch in ch_list:
                    row = row_map.get(ch)
                    if not row:
                        return f"❌ Ch{ch}이(가) config.txt에 없습니다"
                    row['V0Set'] = self._format_numeric(voltage)
                    resolved_channels.append(ch)
            
            self._write_config_rows(rows)
            
            cmd = f"./HVWrappdemo --config {HV_CONFIG_RELATIVE_PATH} --Pw On"
            stdout, stderr = self._run_remote_command(cmd)
            
            output_lines = []
            output_lines.append("🔧 HV Voltage Command Executed")
            
            changes = []
            for identifier, voltage in channel_values.items():
                ch_list = self._resolve_single_identifier(str(identifier), name_to_ch_map)
                for ch in ch_list:
                    changes.append(f"Ch{ch}→{self._format_numeric(voltage)}V")
            output_lines.append(f"📋 Request: {', '.join(sorted(changes))}")
            output_lines.append(f"💻 Command: {cmd}")
            output_lines.append("")
            
            if stdout and stdout.strip():
                output_lines.append("📄 Output:")
                output_lines.extend(stdout.strip().split('\n'))
                output_lines.append("")
            
            if stderr and stderr.strip():
                output_lines.append("⚠️ Stderr:")
                output_lines.extend(stderr.strip().split('\n'))
            
            return "\n".join(output_lines)
        
        else:
            if "channel" in params and "channels" not in params:
                params["channels"] = [params["channel"]]
            if "value" in params and "voltage" not in params:
                params["voltage"] = params["value"]
            
            if "channels" not in params or "voltage" not in params:
                return "❌ channels와 voltage 파라미터가 필요합니다"
            
            try:
                channels = self._parse_channels(params["channels"])
            except ValueError as e:
                return str(e)
            
            if not channels:
                return "❌ 유효한 채널을 찾을 수 없습니다"
            
            voltage = float(params["voltage"])
            
            rows = self._read_config_rows()
            row_map = {row['ch']: row for row in rows}
            
            for ch in channels:
                row = row_map.get(ch)
                if not row:
                    return f"❌ Ch{ch}이(가) config.txt에 없습니다"
                row['V0Set'] = self._format_numeric(voltage)
            
            self._write_config_rows(rows)
            
            cmd = f"./HVWrappdemo --config {HV_CONFIG_RELATIVE_PATH} --Pw On"
            stdout, stderr = self._run_remote_command(cmd)
            
            output_lines = []
            output_lines.append("🔧 HV Voltage Command Executed")
            
            if len(channels) == 1:
                output_lines.append(f"📋 Request: Ch{channels[0]} → {self._format_numeric(voltage)}V")
            else:
                ch_list = ", ".join(f"Ch{ch}" for ch in channels)
                output_lines.append(f"📋 Request: {ch_list} → {self._format_numeric(voltage)}V")
            output_lines.append(f"💻 Command: {cmd}")
            output_lines.append("")
            
            if stdout and stdout.strip():
                output_lines.append("📄 Output:")
                output_lines.extend(stdout.strip().split('\n'))
                output_lines.append("")
            
            if stderr and stderr.strip():
                output_lines.append("⚠️ Stderr:")
                output_lines.extend(stderr.strip().split('\n'))
            
            return "\n".join(output_lines)
    
    def _set_current(self, params: Dict[str, Any]) -> str:
        """전류 설정"""
        if "channel_values" in params:
            channel_values = params["channel_values"]
            if not channel_values:
                return "❌ channel_values가 비어있습니다"
            
            rows = self._read_config_rows()
            row_map = {row['ch']: row for row in rows}
            try:
                name_to_ch_map = self._get_name_to_channel_map(rows)
            except ValueError as e:
                return str(e)
            
            resolved_channels = []
            for identifier, current in channel_values.items():
                ch_list = self._resolve_single_identifier(str(identifier), name_to_ch_map)
                if not ch_list:
                    return f"❌ '{identifier}'에 해당하는 채널을 찾을 수 없습니다"
                
                for ch in ch_list:
                    row = row_map.get(ch)
                    if not row:
                        return f"❌ Ch{ch}이(가) config.txt에 없습니다"
                    row['I0Set'] = self._format_numeric(current)
                    resolved_channels.append(ch)
            
            self._write_config_rows(rows)
            
            cmd = f"./HVWrappdemo --config {HV_CONFIG_RELATIVE_PATH} --Pw On"
            stdout, stderr = self._run_remote_command(cmd)
            
            output_lines = []
            output_lines.append("🔧 HV Current Command Executed")
            
            changes = []
            for identifier, current in channel_values.items():
                ch_list = self._resolve_single_identifier(str(identifier), name_to_ch_map)
                for ch in ch_list:
                    changes.append(f"Ch{ch}→{self._format_numeric(current)}μA")
            output_lines.append(f"📋 Request: {', '.join(sorted(changes))}")
            output_lines.append(f"💻 Command: {cmd}")
            output_lines.append("")
            
            if stdout and stdout.strip():
                output_lines.append("📄 Output:")
                output_lines.extend(stdout.strip().split('\n'))
                output_lines.append("")
            
            if stderr and stderr.strip():
                output_lines.append("⚠️ Stderr:")
                output_lines.extend(stderr.strip().split('\n'))
            
            return "\n".join(output_lines)
        
        else:
            if "channel" in params and "channels" not in params:
                params["channels"] = [params["channel"]]
            if "value" in params and "current" not in params:
                params["current"] = params["value"]
            
            if "channels" not in params or "current" not in params:
                return "❌ channels와 current 파라미터가 필요합니다"
            
            try:
                channels = self._parse_channels(params["channels"])
            except ValueError as e:
                return str(e)
            
            if not channels:
                return "❌ 유효한 채널을 찾을 수 없습니다"
            
            current = float(params["current"])
            
            rows = self._read_config_rows()
            row_map = {row['ch']: row for row in rows}
            
            for ch in channels:
                row = row_map.get(ch)
                if not row:
                    return f"❌ Ch{ch}이(가) config.txt에 없습니다"
                row['I0Set'] = self._format_numeric(current)
            
            self._write_config_rows(rows)
            
            cmd = f"./HVWrappdemo --config {HV_CONFIG_RELATIVE_PATH} --Pw On"
            stdout, stderr = self._run_remote_command(cmd)
            
            output_lines = []
            output_lines.append("🔧 HV Current Command Executed")
            
            if len(channels) == 1:
                output_lines.append(f"📋 Request: Ch{channels[0]} → {self._format_numeric(current)}μA")
            else:
                ch_list = ", ".join(f"Ch{ch}" for ch in channels)
                output_lines.append(f"📋 Request: {ch_list} → {self._format_numeric(current)}μA")
            output_lines.append(f"💻 Command: {cmd}")
            output_lines.append("")
            
            if stdout and stdout.strip():
                output_lines.append("📄 Output:")
                output_lines.extend(stdout.strip().split('\n'))
                output_lines.append("")
            
            if stderr and stderr.strip():
                output_lines.append("⚠️ Stderr:")
                output_lines.extend(stderr.strip().split('\n'))
            
            return "\n".join(output_lines)
    
    def _power_toggle(self, params: Dict[str, Any], state: str) -> str:
        """전원 On/Off"""
        if "channel" in params and "channels" not in params:
            params["channels"] = [params["channel"]]
        
        if "channels" not in params:
            return "❌ channels 파라미터가 필요합니다"
        
        try:
            channels = self._parse_channels(params["channels"])
        except ValueError as e:
            return str(e)
        
        if not channels:
            return "❌ 유효한 채널을 찾을 수 없습니다"
        
        cmd = f"./HVWrappdemo --config {HV_CONFIG_RELATIVE_PATH} --Pw {state}"
        stdout, stderr = self._run_remote_command(cmd)
        
        output_lines = []
        output_lines.append(f"🔧 HV Power {state} Command Executed")
        
        if len(channels) == 1:
            output_lines.append(f"📋 Request: Ch{channels[0]} → {state}")
        else:
            ch_list = ", ".join(f"Ch{ch}" for ch in channels)
            output_lines.append(f"📋 Request: {ch_list} → {state}")
        output_lines.append(f"💻 Command: {cmd}")
        output_lines.append("")
        
        if stdout and stdout.strip():
            output_lines.append("📄 Output:")
            output_lines.extend(stdout.strip().split('\n'))
            output_lines.append("")
        
        if stderr and stderr.strip():
            output_lines.append("⚠️ Stderr:")
            output_lines.extend(stderr.strip().split('\n'))
        
        return "\n".join(output_lines)
    
    def _get_status(self, params: Dict[str, Any]) -> str:
        """상태 확인"""
        if "channel" in params and "channels" not in params:
            params["channels"] = [params["channel"]]
        
        channels = params.get("channels", "all")
        
        if channels == "all" or channels == "전체":
            ch_arg = "all"
        else:
            try:
                resolved_channels = self._parse_channels(channels)
            except ValueError as e:
                return str(e)
            
            if not resolved_channels:
                return "❌ 유효한 채널을 찾을 수 없습니다"
            
            ch_arg = " ".join(map(str, resolved_channels))
        
        command = f"./HVWrappdemo --ch {ch_arg} --Status --VMon --IMon --V0Set --I0Set"
        stdout, stderr = self._run_remote_command(command)
        
        output_lines = []
        output_lines.append("📊 HV Status Query")
        output_lines.append(f"📋 Request: Channels {ch_arg}")
        output_lines.append(f"💻 Command: {command}")
        output_lines.append(f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        output_lines.append("")
        
        if stdout and stdout.strip():
            output_lines.append("📄 Output:")
            output_lines.extend(stdout.strip().split('\n'))
            output_lines.append("")
        
        if stderr and stderr.strip():
            output_lines.append("⚠️ Stderr:")
            output_lines.extend(stderr.strip().split('\n'))
        
        return "\n".join(output_lines)
    
    # ===== SSH 및 Config 관리 헬퍼 함수들 =====
    
    def _ensure_connection(self) -> bool:
        """SSH 연결 확인 및 재연결"""
        try:
            if (self.ssh_client and
                self.ssh_client.get_transport() and
                self.ssh_client.get_transport().is_active()):
                return True
        except Exception:
            pass
        
        return self._connect_ssh()
    
    def _connect_ssh(self) -> bool:
        """SSH 연결"""
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            if HV_SSH_CONFIG['key_path']:
                key = paramiko.RSAKey.from_private_key_file(HV_SSH_CONFIG['key_path'])
                self.ssh_client.connect(
                    hostname=HV_SSH_CONFIG['host'],
                    port=HV_SSH_CONFIG['port'],
                    username=HV_SSH_CONFIG['username'],
                    pkey=key,
                    timeout=10
                )
            else:
                self.ssh_client.connect(
                    hostname=HV_SSH_CONFIG['host'],
                    port=HV_SSH_CONFIG['port'],
                    username=HV_SSH_CONFIG['username'],
                    password=HV_SSH_CONFIG['password'],
                    timeout=10
                )
            return True
        except Exception:
            return False
    
    def _run_remote_command(self, command: str) -> Tuple[str, str]:
        """원격 명령 실행"""
        command_segments = [
            f"cd {shlex.quote(HV_WRAPPER_WORKDIR)}",
            HV_ENV_PRE_COMMAND,
            command
        ]
        remote_cmd = " && ".join(command_segments)
        wrapped = f'bash -c {shlex.quote(remote_cmd)}'
        
        stdin, stdout, stderr = self.ssh_client.exec_command(wrapped, timeout=30)
        output = stdout.read().decode('utf-8', errors='ignore').strip()
        error = stderr.read().decode('utf-8', errors='ignore').strip()
        
        return output, error
    
    def _read_config_rows(self) -> List[Dict[str, Any]]:
        """config.txt 읽기"""
        sftp = self.ssh_client.open_sftp()
        try:
            with sftp.open(HV_CONFIG_FULL_PATH, 'r') as f:
                content = f.read().decode('utf-8', errors='ignore')
        finally:
            sftp.close()
        
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        rows = []
        in_channel_section = False
        
        for line in lines:
            if line.startswith('#'):
                continue
            if line.startswith('ch ') or line.startswith('ch\t'):
                in_channel_section = True
                continue
            if not in_channel_section:
                continue
            
            parts = line.split()
            if len(parts) < 4:
                continue
            
            try:
                ch_str = parts[0]
                match = re.match(r'^(\d+)', ch_str)
                ch = int(match.group(1)) if match else int(ch_str)
            except (ValueError, AttributeError):
                continue
            
            rows.append({
                'ch': ch,
                'ch_str': ch_str,
                'name': parts[1],
                'V0Set': parts[2],
                'I0Set': parts[3]
            })
        
        return rows
    
    def _write_config_rows(self, rows: List[Dict[str, Any]]):
        """config.txt 쓰기"""
        sftp = self.ssh_client.open_sftp()
        try:
            with sftp.open(HV_CONFIG_FULL_PATH, 'r') as f:
                content = f.read().decode('utf-8', errors='ignore')
            
            original_lines = content.splitlines()
            header_lines = []
            channel_header_idx = -1
            
            for idx, line in enumerate(original_lines):
                stripped = line.strip()
                if stripped.startswith('ch ') or stripped.startswith('ch\t'):
                    channel_header_idx = idx
                    break
                header_lines.append(line)
            
            new_lines = header_lines
            if channel_header_idx >= 0:
                new_lines.append(original_lines[channel_header_idx])
            else:
                new_lines.append("ch name V0Set I0Set")
            
            for row in sorted(rows, key=lambda r: r['ch']):
                ch_id = row.get('ch_str', str(row['ch']))
                line = f"{ch_id} {row['name']} {row['V0Set']} {row['I0Set']}"
                new_lines.append(line)
            
            temp_path = f"{HV_CONFIG_FULL_PATH}.tmp"
            with sftp.open(temp_path, 'w') as f:
                f.write("\n".join(new_lines) + "\n")
            
            try:
                sftp.remove(HV_CONFIG_FULL_PATH)
            except FileNotFoundError:
                pass
            sftp.rename(temp_path, HV_CONFIG_FULL_PATH)
        
        finally:
            sftp.close()
    
    def _get_name_to_channel_map(self, rows: List[Dict[str, Any]]) -> Dict[str, List[int]]:
        """
        Name → 채널 번호 리스트 매핑 생성
        - None인 채널은 제외
        - 중복 Name이 있으면 에러 발생
        - 대소문자 구분 없음
        """
        name_map = {}
        
        for row in rows:
            name = row.get('name', '').strip()
            ch = row['ch']
            
            if not name or name.lower() == 'none':
                continue
            
            name_key = name.upper()
            
            if name_key not in name_map:
                name_map[name_key] = []
            name_map[name_key].append(ch)
        
        duplicates = {name: ch_list for name, ch_list in name_map.items() if len(ch_list) > 1}
        if duplicates:
            dup_info = ', '.join([f"{name}(Ch{',Ch'.join(map(str, ch_list))})" 
                                 for name, ch_list in duplicates.items()])
            raise ValueError(f"❌ 중복된 Name이 있습니다: {dup_info}")
        
        # 리스트를 단일 값으로 변환 (중복이 없으므로)
        return {name: ch_list[0] if len(ch_list) == 1 else ch_list 
                for name, ch_list in name_map.items()}
    
    def _resolve_single_identifier(self, identifier: str, name_to_ch_map: Dict[str, Any]) -> List[int]:
        """단일 식별자(Name 또는 채널 번호)를 채널 번호 리스트로 변환"""
        identifier = str(identifier).strip()
        
        if re.match(r'^\d+', identifier):
            try:
                return [int(identifier)]
            except ValueError:
                return []
        
        name_key = identifier.upper()
        if name_key in name_to_ch_map:
            ch = name_to_ch_map[name_key]
            return [ch] if isinstance(ch, int) else ch
        
        return []
    
    def _parse_channels(self, channels: Any) -> List[int]:
        """채널 표현을 리스트로 변환 (번호/Name 모두 지원, 대소문자 무시)"""
        rows = self._read_config_rows()
        name_to_ch_map = self._get_name_to_channel_map(rows)
        
        if isinstance(channels, list):
            result = []
            for item in channels:
                ch_list = self._resolve_single_identifier(str(item), name_to_ch_map)
                result.extend(ch_list)
            return sorted(set(result))
        
        expr = str(channels).strip()
        if expr.lower() in {'전체', 'all'}:
            expr = '0-23'
        
        result = []
        for part in expr.split(','):
            part = part.strip()
            if '-' in part:
                start_str, end_str = part.split('-', 1)
                start_str = start_str.strip()
                end_str = end_str.strip()

                if re.match(r'^\d+$', start_str) and re.match(r'^\d+$', end_str):
                    result.extend(range(int(start_str), int(end_str) + 1))
                else:
                    return []
            else:
                ch_list = self._resolve_single_identifier(part, name_to_ch_map)
                result.extend(ch_list)
        
        return sorted(set(result))
    
    def _format_numeric(self, value: Any) -> str:
        """숫자 포맷팅"""
        try:
            num = float(value)
            if abs(num - int(num)) < 1e-6:
                return str(int(num))
            return f"{num}"
        except (TypeError, ValueError):
            return str(value)
    
    def __del__(self):
        """소멸자: SSH 연결 종료"""
        if self.ssh_client:
            self.ssh_client.close()
