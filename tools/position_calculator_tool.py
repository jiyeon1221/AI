#!/usr/bin/env python3
"""Position Calculator — T5 기준 타워 위치 계산"""

import math
from typing import Dict, Any, Optional
from .config_loader import load_config


# ======================= Tower Layout =======================
"""
타워 레이아웃 (3x3 그리드):

    T1  T2  T3
    T4  T5  T6
    T7  T8  T9

T5가 중심이며, 다른 타워들은 SWITCH 함수를 통해 오프셋 계산됨.
"""

VALID_TOWERS = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9"]


# ======================= Position Calculator =======================

class PositionCalculator_Sym:
    """타워 위치 계산기 — 대칭 모듈용 (스프레드시트 수식 구조 반영)"""

    def __init__(self):
        config = load_config()

        pos_scan = config.get("PositionScan") or {}
        pos_consts = config.get("PositionConstants") or {}

        for key in ["OffsetX", "OffsetY", "TowerWidth", "TowerHeight"]:
            if pos_scan.get(key) is None:
                raise RuntimeError(
                    f"config_general.yml PositionScan.{key} 가 정의되지 않았습니다."
                )

        for key in ["RotationAxisAngle", "RotationAxisDist", "CenterToBottom", "AxisToModule"]:
            if pos_consts.get(key) is None:
                raise RuntimeError(
                    f"config_general.yml PositionConstants.{key} 가 정의되지 않았습니다."
                )

        self.offset_x = float(pos_scan["OffsetX"])
        self.offset_y = float(pos_scan["OffsetY"])
        self.tower_width = float(pos_scan["TowerWidth"])
        self.tower_height = float(pos_scan["TowerHeight"])

        self.rotation_axis_angle = float(pos_consts["RotationAxisAngle"])
        self.rotation_axis_dist  = float(pos_consts["RotationAxisDist"])
        self.center_to_bottom    = float(pos_consts["CenterToBottom"])
        self.axis_to_module      = float(pos_consts["AxisToModule"])

        self.rotation = 0.0
        self.tilting = 0.0

    def _tower_offset_x(self, tower: str) -> float:
        """
        타워별 X 방향 오프셋 (B43 수식)

        SWITCH(B6,
          "T1", B41, "T4", B41, "T7", B41,
          "T2", 0,   "T5", 0,   "T8", 0,
          "T3", -B41, "T6", -B41, "T9", -B41)
        """
        if tower in ("T1", "T4", "T7"):
            return self.tower_width
        if tower in ("T3", "T6", "T9"):
            return -self.tower_width
        return 0.0

    def _tower_offset_y(self, tower: str) -> float:
        """
        타워별 Y 방향 오프셋 (C43 수식)

        SWITCH(B6,
          "T1", -C41, "T2", -C41, "T3", -C41,
          "T4", 0,    "T5", 0,    "T6", 0,
          "T7", C41,  "T8", C41,  "T9", C41)
        """
        if tower in ("T1", "T2", "T3"):
            return -self.tower_height
        if tower in ("T7", "T8", "T9"):
            return self.tower_height
        return 0.0

    def calculate_tower_position(self, tower: str,
                                 rotation: Optional[float] = None,
                                 tilting: Optional[float] = None) -> Dict[str, float]:
        """
        특정 타워의 중심 위치 계산 (Rotation/Tilting 적용)

        계산 구조:
        - B43 = 타워별 X 오프셋 (SWITCH 함수)
        - C43 = 타워별 Y 오프셋 (SWITCH 함수, ±TowerHeight)
        - x = B43 + offset_x + rotation_term
        - y = offset_y + C43 * cos(θ)
              - ( center_to_bottom * cos(θ) + axis_to_module * sin(θ) - center_to_bottom )
        """
        tower = tower.upper()
        if tower not in VALID_TOWERS:
            raise ValueError(f"유효하지 않은 타워: {tower}. {VALID_TOWERS} 중 하나여야 합니다.")

        if rotation is None:
            rotation = self.rotation
        if tilting is None:
            tilting = self.tilting

        b45 = self._tower_offset_x(tower)  # B45 = B43
        c45 = self._tower_offset_y(tower)  # C45 = C43

        # Rotation 보정 (B46)
        if rotation != 0.0:
            base_rad = math.radians(self.rotation_axis_angle)
            rot_rad = math.radians(rotation)
            rotation_term = (self.rotation_axis_dist * math.sin(base_rad + rot_rad)
                             - self.rotation_axis_dist * math.sin(base_rad))
            x = b45 + self.offset_x + rotation_term
        else:
            x = b45 + self.offset_x

        # Tilting 보정 (C46)
        tilt_rad = math.radians(tilting)
        tilting_correction = (
            self.center_to_bottom * math.cos(tilt_rad)
            + self.axis_to_module * math.sin(tilt_rad)
            - self.center_to_bottom
        )
        y = self.offset_y + c45 * math.cos(tilt_rad) - tilting_correction

        return {"x": x, "y": y}

    def calculate_all_positions(self, rotation: Optional[float] = None,
                                tilting: Optional[float] = None) -> Dict[str, Dict[str, float]]:
        """모든 타워의 위치 계산"""
        return {
            tower: self.calculate_tower_position(tower, rotation, tilting)
            for tower in VALID_TOWERS
        }

    def get_status(self) -> Dict[str, Any]:
        """현재 상태 확인"""
        return {
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "tower_spacing": {
                "x": self.tower_width,
                "y": self.tower_height,
            },
            "constants": {
                "rotation_axis_angle": self.rotation_axis_angle,
                "rotation_axis_dist":  self.rotation_axis_dist,
                "center_to_bottom":    self.center_to_bottom,
                "axis_to_module":      self.axis_to_module,
            },
            "all_positions": self.calculate_all_positions(),
        }


# ======================= Unsymmetric Position Calculator =======================

class PositionCalculator:
    """
    타워 위치 계산기 — 비대칭 모듈용

    모듈 크기가 모두 다를 경우 사용.
    TowerWidth/TowerHeight 기반 균일 간격 대신,
    센터 타워(T5)로부터 각 타워까지의 x,y 거리를 아래 TOWER_OFFSETS에 직접 기재한다.

    Rotation/Tilting 보정 방식은 PositionCalculator와 동일.
    """

    # ── 타워별 T5 기준 상대 거리 (mm) ── 직접 수정하세요 ──────────────────
    #   T1  T2  T3
    #   T4  T5  T6
    #   T7  T8  T9
    TOWER_OFFSETS: Dict[str, Dict[str, float]] = {
        "T1": {"dx":  46.75, "dy":  -49.0},
        "T2": {"dx":  0.5, "dy":  -46.75},
        "T3": {"dx":  -44.75, "dy":  -48.5},
        "T4": {"dx":  44.75, "dy":  0.5},
        "T5": {"dx":  0.0, "dy":  0.0},
        "T6": {"dx":  -45.0, "dy":  0.5},
        "T7": {"dx":  45.75, "dy":  50.25},
        "T8": {"dx":  -0.25, "dy":  47.5},
        "T9": {"dx":  -45.5, "dy": 49.75},
    }
    # ──────────────────────────────────────────────────────────────────────

    def __init__(self):
        config = load_config()

        pos_scan   = config.get("PositionScan")    or {}
        pos_consts = config.get("PositionConstants") or {}

        for key in ["OffsetX", "OffsetY"]:
            if pos_scan.get(key) is None:
                raise RuntimeError(
                    f"config_general.yml PositionScan.{key} 가 정의되지 않았습니다."
                )

        for key in ["RotationAxisAngle", "RotationAxisDist", "CenterToBottom", "AxisToModule"]:
            if pos_consts.get(key) is None:
                raise RuntimeError(
                    f"config_general.yml PositionConstants.{key} 가 정의되지 않았습니다."
                )

        self.offset_x = float(pos_scan["OffsetX"])
        self.offset_y = float(pos_scan["OffsetY"])

        self.rotation_axis_angle = float(pos_consts["RotationAxisAngle"])
        self.rotation_axis_dist  = float(pos_consts["RotationAxisDist"])
        self.center_to_bottom    = float(pos_consts["CenterToBottom"])
        self.axis_to_module      = float(pos_consts["AxisToModule"])

        self.rotation = 0.0
        self.tilting  = 0.0

    def calculate_tower_position(self, tower: str,
                                  rotation: Optional[float] = None,
                                  tilting: Optional[float] = None) -> Dict[str, float]:
        """
        특정 타워의 중심 위치 계산 (Rotation/Tilting 적용)

        계산 구조:
        - dx, dy = TOWER_OFFSETS[tower]  (T5 기준 상대 거리)
        - x = offset_x + dx + rotation_term
        - y = offset_y + dy * cos(θ)
              - ( center_to_bottom * cos(θ) + axis_to_module * sin(θ) - center_to_bottom )
        """
        tower = tower.upper()
        if tower not in VALID_TOWERS:
            raise ValueError(f"유효하지 않은 타워: {tower}. {VALID_TOWERS} 중 하나여야 합니다.")

        if rotation is None:
            rotation = self.rotation
        if tilting is None:
            tilting = self.tilting

        dx = self.TOWER_OFFSETS[tower]["dx"]
        dy = self.TOWER_OFFSETS[tower]["dy"]

        # Rotation 보정
        if rotation != 0.0:
            base_rad = math.radians(self.rotation_axis_angle)
            rot_rad  = math.radians(rotation)
            rotation_term = (self.rotation_axis_dist * math.sin(base_rad + rot_rad)
                             - self.rotation_axis_dist * math.sin(base_rad))
            x = dx + self.offset_x + rotation_term
        else:
            x = dx + self.offset_x

        # Tilting 보정
        tilt_rad = math.radians(tilting)
        tilting_correction = (
            self.center_to_bottom * math.cos(tilt_rad)
            + self.axis_to_module * math.sin(tilt_rad)
            - self.center_to_bottom
        )
        y = self.offset_y + dy * math.cos(tilt_rad) - tilting_correction

        return {"x": x, "y": y}

    def calculate_all_positions(self, rotation: Optional[float] = None,
                                 tilting: Optional[float] = None) -> Dict[str, Dict[str, float]]:
        """모든 타워의 위치 계산"""
        return {
            tower: self.calculate_tower_position(tower, rotation, tilting)
            for tower in self.TOWER_OFFSETS
        }

    def get_status(self) -> Dict[str, Any]:
        """현재 상태 확인"""
        return {
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "tower_offsets": self.TOWER_OFFSETS,
            "constants": {
                "rotation_axis_angle": self.rotation_axis_angle,
                "rotation_axis_dist":  self.rotation_axis_dist,
                "center_to_bottom":    self.center_to_bottom,
                "axis_to_module":      self.axis_to_module,
            },
            "all_positions": self.calculate_all_positions(),
        }


# ======================= Global Calculator =======================

_position_calculator = PositionCalculator_Sym()


# ======================= Direct Access Functions =======================

def calculate_position(tower: str) -> Dict[str, float]:
    """직접 접근용 함수 (tool decorator 없이)"""
    return _position_calculator.calculate_tower_position(tower)


def get_calculator() -> "PositionCalculator_Sym":
    """Calculator 객체 직접 접근"""
    return _position_calculator
