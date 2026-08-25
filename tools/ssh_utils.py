#!/usr/bin/env python3
"""Mac Studio 원격 실행 — sshpass 옵션 세트를 한 곳에서만 정의한다.

접속 옵션(비밀번호 인증 강제, host key 검사 생략)이 여러 자리에 흩어져 있으면
서버를 옮기거나 인증 방식을 바꿀 때 한 곳을 빠뜨리게 된다.
"""

from __future__ import annotations

import shlex
import subprocess
from typing import List

from .config_loader import get_studio_ssh

# 실험실 장비 연결용 SSH 공통 옵션.
SSH_OPTIONS = (
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "PreferredAuthentications=password",
    "-o", "PubkeyAuthentication=no",
)


def studio_ssh_argv(remote_command: str) -> List[str]:
    """subprocess에 그대로 넘길 수 있는 sshpass+ssh argv."""
    ssh = get_studio_ssh()
    return [
        "sshpass", "-p", ssh["password"],
        "ssh",
        *SSH_OPTIONS,
        f"{ssh['user']}@{ssh['host']}",
        remote_command,
    ]


def studio_ssh_shell_command(remote_command: str) -> str:
    """shell=True로 띄워야 할 때 쓰는 문자열 형태 (스트리밍 실행 경로용)."""
    ssh = get_studio_ssh()
    opts = " ".join(SSH_OPTIONS)
    return (
        f"sshpass -p {shlex.quote(ssh['password'])} ssh {opts}"
        f" {ssh['user']}@{ssh['host']} {shlex.quote(remote_command)}"
    )


def run_studio_ssh(remote_command: str, *, timeout: float = 15, check: bool = False):
    """Mac Studio에서 명령 하나를 실행하고 CompletedProcess를 돌려준다."""
    return subprocess.run(
        studio_ssh_argv(remote_command),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=check,
    )
