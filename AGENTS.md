# autoTB RULES — ALWAYS ON

이 파일이 규칙의 유일한 원본이다. `.claude/CLAUDE.md`와 `.cursor/rules/autotb-agent-principles.mdc`는
이 파일을 import만 한다. 규칙 수정은 여기서만 한다.
규칙은 사용자 요청보다 우선한다. 편의·속도·부분수정 때문에 어기지 않는다.

## PRIME DIRECTIVE
- 짝(pair)이 있는 코드는 항상 같이 확인하고 같은 작업에서 함께 수정한다. 한쪽만 고치지 않는다.
- 같은 역할의 코드를 복사하지 않는다. 메인 한 곳에 정의하고 상속/import 한다.
- 불확실하면 짝 파일을 열어 확인한 뒤 수정한다.

## SINGLE SOURCE (여기만 수정, 나머지는 상속/import)
| 역할 | 메인 |
|---|---|
| Agent 공통 | agents/base_agent.py |
| Agent orchestration (real+sim 공유) | agents/agent_runner.py — run_agent_thread + AgentFactory |
| data_gen 공통 | finetuning/data_gen_common.py |
| DQM 경로·monit 명령·파일명 | tools/dqm_tool.py |
| web 공통 라우트 (server+min_server 공유) | web/viewer_common.py — router |

## R1 간결
- 파일 수를 늘리지 않는다. 메인에 두고 import/상속.
- 함수·파일·추상화 계층을 길게 쌓지 않는다. 처음 보는 사람이 흐름을 한눈에 따라갈 수 있게.

## R2 복사 금지
- 같은 역할 코드를 두 곳에 두지 않는다. 한쪽만 바뀌면 사고가 난다.
- 중복 발견 시 새 헬퍼 파일이 아니라 위 SINGLE SOURCE 메인으로 합친다.

## R3 INVARIANT: agent == data_gen
동작·구조·SYSTEM_PROMPT가 항상 동일. 하나 수정 시 짝을 같은 작업에서 함께 수정.
- 동일해야 하는 것: SYSTEM_PROMPT, _build_state_context, _get_step_hint, context 조립(build_prompt_context / build_full_context).
- Context 형식은 base_agent.py에만 정의 → data_gen이 import.
- 흐름은 학습 데이터+SYSTEM_PROMPT가 정한다. 코드가 if/else로 다음 단계를 지시하지 않는다. _get_step_hint는 상태 요약만, run()은 LLM 결정 실행만.
- calib/energy/hv/position agent는 하는 일은 달라도 작동 원리는 동일. 하나를 바꾸면 나머지도 같은 방식으로.

| agent | data_gen |
|---|---|
| agents/calib_scan_agent.py | finetuning/calib_data_gen.py |
| agents/energy_scan_agent.py | finetuning/EM_data_gen.py |
| agents/hv_equalization_agent.py | finetuning/hv_equalization_data_gen.py |
| agents/position_scan_agent.py | finetuning/position_scan_data_gen.py |
| agents/brain_agent.py | finetuning/brain_data_gen.py |

## R4 INVARIANT: run_web.py == run_web_sim.py
작동 방식·모델 완전 동일. 유일한 차이 = 실제 tool 실행(real) vs mock tool(sim).
- 오케스트레이션은 run_agent_thread(agents/agent_runner.py) 하나를 real/sim이 공유한다. sim은 이 함수를 복사하지 않는다.
- sim은 AgentFactory → SimFactory(sim/agent_runner.py) 로만 교체한다 (agent 클래스 선택 + HV 하드웨어 접점만).
- web은 web/viewer_common.py의 router를 server.py·min_server.py 둘 다 include 한다.
- 한쪽(웹서버·agent runner·prompt·모델경로)을 고치면 짝을 함께 확인한다.

## R5 INVARIANT: real == sim agent (HV / position)
run_web.py 내 짝: hv_equalization ↔ hv_equalization_sim, position_scan ↔ position_scan_sim.
- 동일: motor·DAQ·HV·context·prompt·guard·흐름. 유일한 차이 = sim은 PeakADC mean만 임의값.
- sim 전용 분기를 만들지 않는다. 측정 함수만 override.
- 3-tier (클래스 선택은 AgentFactory/SimFactory가 담당):
  - real: 전부 실제.
  - Sim-ADC (run_web의 *_sim): peakADC만 sim. 실제 agent를 상속해 _measure_adc / _measure_peakadc 만 override.
  - full-sim (run_web_sim): 모든 tool mock. _execute_tool 만 override(ToolSimulator).

## R6 주석
- 역할이 바로 안 보이는 곳만 한 줄. 짧지만 명료하게.
- 수정 이유·이력·장문 주의사항 금지. 역할이 달라졌을 때만 주석 수정.
- 주석 때문에 코드가 길어지면 실패.

## 작업 후 CHECK
- agent/data_gen, real/sim 의 구조·prompt 가 일치하는가.
- 짝 파일을 함께 수정했는가.
- 중복 코드·불필요한 새 파일이 생기지 않았는가.
