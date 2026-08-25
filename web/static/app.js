/* WebSocket 연결. */
let ws = null;
let awaitingInput = false;         // 에이전트 입력 대기 여부.
let _awaitingInterrupted = false;  // 입력 대기 중 사용자 메시지 전송 여부.
let _lastAgentMsg = null;          // 입력 대기 직전 AI 메시지.

/* 위·아래 키로 탐색하는 명령 기록. */
const _cmdHistory = [];
let _histIdx = -1;       // -1이면 기록을 탐색하지 않는다.
let _histDraft = '';     // 탐색 전 작성 중이던 입력.
let activeAgent = null;
let _pendingAdhocClear = false;   // 다음 별도 요청 팝업을 열 때 내용을 지운다.

function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/ws`);

  ws.onopen = () => setStatus('연결됨', '');

  ws.onmessage = (evt) => {
    _msgQueue.push(JSON.parse(evt.data));
    if (!_rafPending) {
      _rafPending = true;
      requestAnimationFrame(_flushQueue);
    }
  };

  ws.onclose = () => {
    setStatus('연결 끊김', 'error');
    setTimeout(connectWS, 2000);   // 2초 후 다시 연결한다.
  };

  ws.onerror = () => ws.close();
}

function send(obj) {
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(JSON.stringify(obj));
}

/* 화면 프레임 단위 메시지 큐. */
let _msgQueue   = [];
let _rafPending = false;
let _scrollTargets = new Set();

function _flushQueue() {
  _rafPending = false;
  const msgs = _msgQueue.splice(0);
  for (const msg of msgs) handleMessage(msg);
  _scrollTargets.forEach(el => { el.scrollTop = el.scrollHeight; });
  _scrollTargets.clear();
}

/* 서버 메시지 처리. */
function handleMessage(msg) {
  const isBrain = msg.source === 'brain';

  switch (msg.type) {

    case 'ai_message':
      appendAI(msg.content, isBrain);
      break;

    case 'tool_output':
      if (isBrain) {
        openAdhoc();
        adhocAppendToolOutput(msg.content);
      } else {
        appendToolOutput(msg.content);
      }
      break;

    case 'plot':
      if (isBrain) {
        adhocAppendPlot(msg.filename);   // 함수 내부에서 팝업을 연다.
      } else {
        appendPlot(msg.filename);
      }
      break;

    case 'html_content':
      if (isBrain) {
        openAdhoc();
        adhocAppendHtml(msg.content);
      } else {
        appendHtml(msg.content);
      }
      break;

    case 'dqm_canvases':
      if (isBrain) {
        openAdhoc();
        adhocDrawDqmCanvases(msg.base_prefix, msg.canvases);
      }
      break;

    case 'adhoc_clarify':
      showClarifyInChat(msg.question || '');
      break;

    case 'adhoc_confirm':
      adhocShowConfirm(msg.preview || '', msg.tool || '', !!msg.scenario_running);
      break;

    case 'awaiting_input':
      awaitingInput = true;
      _lastAgentMsg = _pendingAgentMsg;
      addCompleteButton();
      break;

    case 'awaiting_hv_confirm':
      awaitingInput = true;
      _lastAgentMsg = _pendingAgentMsg;
      addHvConfirmButtons();
      break;

    case 'status':
      if (!isBrain) {
        setStatus(msg.content, msg.content.includes('완료') ? '' : 'running');
      }
      break;

    case 'daq_complete':
      console.log('[autoTB] daq_complete received');
      playDaqCompleteSound();
      break;

    case 'agent_done':
      awaitingInput = false;
      removeCompleteButtons();
      document.querySelectorAll('.inline-retry-btn').forEach(btn => {
        btn.disabled = true;
        btn.textContent = '종료됨';
      });
      setAgentButtons(false);
      activeAgent = null;
      setStatus('대기 중', '');
      break;

    case 'open_window':
      adhocAppendLink(msg.url, msg.label || msg.url);
      break;

    case 'dqm_live_start':
      dqmLiveStart(msg);
      break;

    case 'dqm_refresh':
      dqmRefresh(msg);
      break;

    case 'dqm_live_end':
      dqmLiveEnd(msg);
      break;

    case 'error':
      if (isBrain) {
        adhocAppendToolOutput('❌ ' + msg.content, true);
      } else {
        appendToolOutput('❌ ' + msg.content, true);
      }
      break;

    case 'tool_error':
      appendToolError(msg.tool_name, msg.error, msg.attempts, isBrain);
      break;
  }
}

/* 사용자 동작. */
function addCompleteButton() {
  removeCompleteButtons();   // 완료 버튼은 하나만 표시한다.
  const row = document.createElement('div');
  row.className = 'complete-row';

  if (_awaitingInterrupted && _lastAgentMsg && !_lastAgentMsg.isBrain) {
    _awaitingInterrupted = false;
    appendAI(_lastAgentMsg.text, _lastAgentMsg.isBrain);
  } else {
    _awaitingInterrupted = false;
  }

  const btn = document.createElement('button');
  btn.className = 'inline-complete-btn';
  btn.textContent = '✔ 완료';
  btn.onclick = sendComplete;
  row.appendChild(btn);
  chatScroll().appendChild(row);
  scrollBottom(chatScroll());
}

function removeCompleteButtons() {
  chatScroll().querySelectorAll('.complete-row').forEach(el => el.remove());
}

function addHvConfirmButtons() {
  removeCompleteButtons();
  const row = document.createElement('div');
  row.className = 'complete-row hv-confirm-row';

  if (_awaitingInterrupted && _lastAgentMsg && !_lastAgentMsg.isBrain) {
    _awaitingInterrupted = false;
    appendAI(_lastAgentMsg.text, _lastAgentMsg.isBrain);
  } else {
    _awaitingInterrupted = false;
  }

  const doneBtn = document.createElement('button');
  doneBtn.className = 'inline-complete-btn';
  doneBtn.textContent = '✔ 완료';
  doneBtn.onclick = sendComplete;

  const modBtn = document.createElement('button');
  modBtn.className = 'inline-modify-btn';
  modBtn.textContent = '✏ 수정';

  const modArea = document.createElement('div');
  modArea.className = 'hv-modify-area';
  modArea.style.display = 'none';

  const modInput = document.createElement('input');
  modInput.type = 'text';
  modInput.className = 'hv-modify-input';
  modInput.placeholder = '예) C 30 올려  /  모두 40 올려  /  C=790';

  const sendBtn = document.createElement('button');
  sendBtn.className = 'inline-complete-btn';
  sendBtn.textContent = '전송';
  sendBtn.onclick = () => {
    const text = modInput.value.trim();
    if (!text) return;
    removeCompleteButtons();
    awaitingInput = false;
    appendUserBubble(text);
    send({ type: 'user_input', content: text });
  };

  modInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') sendBtn.click();
  });

  modBtn.onclick = () => {
    modArea.style.display = modArea.style.display === 'none' ? 'flex' : 'none';
    if (modArea.style.display === 'flex') modInput.focus();
  };

  modArea.appendChild(modInput);
  modArea.appendChild(sendBtn);
  row.appendChild(doneBtn);
  row.appendChild(modBtn);
  row.appendChild(modArea);
  chatScroll().appendChild(row);
  scrollBottom(chatScroll());
}

function sendComplete() {
  removeCompleteButtons();
  awaitingInput = false;
  appendUserBubble('완료');
  send({ type: 'user_input', content: '완료' });
}

function sendText() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text) return;
  // 연속 중복을 제외하고 명령 기록에 저장한다.
  if (_cmdHistory[0] !== text) _cmdHistory.unshift(text);
  _histIdx = -1;
  _histDraft = '';
  input.value = '';
  _pendingAdhocClear = true;   // 다음 팝업에서 이전 결과를 지운다.
  appendUserBubble(text);
  send({ type: 'user_input', content: text });
  // 입력 대기 중이면 인라인 완료 버튼도 제거한다.
  if (awaitingInput) _awaitingInterrupted = true;
  removeCompleteButtons();
  awaitingInput = false;
}

function startAgent(agentName) {
  if (activeAgent) {
    alert('에이전트가 이미 실행 중입니다. 먼저 Stop을 클릭하세요.');
    return;
  }
  const needsTowerPick = ['em_scan', 'calib_scan', 'hv_equalization', 'hv_equalization_sim', 'position_scan', 'position_scan_sim'];
  if (needsTowerPick.includes(agentName)) {
    openTowerPicker(agentName);
    return;
  }
  _launchAgent(agentName, {});
}

function _launchAgent(agentName, params) {
  clearPanels();
  activeAgent = agentName;
  setAgentButtons(true);
  setStatus(`${agentName} 에이전트 실행 중`, 'running');
  send({ type: 'start_agent', agent: agentName, params });
}

function stopAgent() {
  send({ type: 'stop_agent' });
}

function killRun() {
  const btn = document.getElementById('kill-btn');
  btn.disabled = true;
  send({ type: 'kill_run' });
  setTimeout(() => { btn.disabled = false; }, 2000);
}

function openHvCheck() {
  window.open('/hv/check', '_blank', 'width=1100,height=820');
}

/* DOM 항목 수 제한. */
const MAX_BLOCK_LINES  = 400;   // tool-block 한 개 내 최대 줄 수
const MAX_TOOL_BLOCKS  = 80;    // right-scroll 최대 블록 수
const MAX_CHAT_NODES   = 120;   // chat-scroll 최대 노드 수
const MAX_ADHOC_NODES  = 80;    // adhoc-scroll 최대 노드 수

function trimContainer(el, max) {
  while (el.childElementCount > max)
    el.removeChild(el.firstElementChild);
}

function trimBlockLines(block) {
  const lines = block.textContent.split('\n');
  if (lines.length > MAX_BLOCK_LINES)
    block.textContent = lines.slice(-Math.floor(MAX_BLOCK_LINES / 2)).join('\n');
}

/* 화면 초기화 함수. */
function clearToolOutput() { rightScroll().innerHTML = ''; }
function clearChat()       { chatScroll().innerHTML = ''; }
function clearAdhoc()      { adhocScroll().innerHTML = ''; }

/* DOM 보조 함수. */
let _pendingAgentMsg = null;  // 다시 표시할 수 있는 마지막 AI 메시지.

function appendAI(text, isBrain = false) {
  _pendingAgentMsg = { text, isBrain };
  const div = document.createElement('div');
  div.className = isBrain ? 'ai-bubble brain-bubble' : 'ai-bubble';
  if (isBrain) {
    const tag = document.createElement('span');
    tag.className = 'brain-tag';
    tag.textContent = 'Background';
    div.appendChild(tag);
    div.appendChild(document.createTextNode(' ' + text));
  } else {
    div.textContent = text;
  }
  chatScroll().appendChild(div);
  trimContainer(chatScroll(), MAX_CHAT_NODES);
  scrollBottom(chatScroll());
}

/* 채팅 내부 추가 질문 폼. */
function showClarifyInChat(question) {
  const div = document.createElement('div');
  div.className = 'ai-bubble brain-bubble clarify-inline';

  const qLine = document.createElement('div');
  const tag = document.createElement('span');
  tag.className = 'brain-tag';
  tag.textContent = '추가 정보 필요';
  qLine.appendChild(tag);
  qLine.appendChild(document.createTextNode(' ' + question));
  div.appendChild(qLine);

  const row = document.createElement('div');
  row.className = 'clarify-inline-row';

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'clarify-inline-input';
  input.placeholder = '답변을 입력하세요...';

  const btn = document.createElement('button');
  btn.className = 'clarify-inline-send';
  btn.textContent = '전송';

  const submit = () => {
    const text = input.value.trim();
    if (!text) return;
    input.disabled = true;
    btn.disabled = true;
    appendUserBubble(text);
    send({ type: 'user_input', content: text });
  };

  btn.onclick = submit;
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') { e.preventDefault(); submit(); }
  });

  row.appendChild(input);
  row.appendChild(btn);
  div.appendChild(row);

  chatScroll().appendChild(div);
  trimContainer(chatScroll(), MAX_CHAT_NODES);
  scrollBottom(chatScroll());
  setTimeout(() => input.focus(), 50);
}

function appendUserBubble(text) {
  const div = document.createElement('div');
  div.className = 'user-bubble';
  div.textContent = text;
  chatScroll().appendChild(div);
  trimContainer(chatScroll(), MAX_CHAT_NODES);
  scrollBottom(chatScroll());
}

function appendToolError(toolName, errorMsg, attempts, isBrain = false) {
  const div = document.createElement('div');
  div.className = 'tool-error-bubble';
  const title = document.createElement('span');
  title.className = 'tool-error-title';
  title.textContent = `Tool 오류: ${toolName}`;
  div.appendChild(title);
  div.appendChild(document.createTextNode(`${attempts}회 시도 모두 실패\n${errorMsg}`));
  chatScroll().appendChild(div);

  const retryRow = document.createElement('div');
  retryRow.className = 'retry-row';

  const retryBtn = document.createElement('button');
  retryBtn.className = 'inline-retry-btn';
  retryBtn.textContent = '↻ 다시 시도';

  const skipBtn = isBrain ? null : document.createElement('button');
  if (skipBtn) {
    skipBtn.className = 'inline-retry-btn inline-skip-btn';
    skipBtn.textContent = '→ 다음 단계로';
  }

  const disableBoth = () => {
    retryBtn.disabled = true;
    if (skipBtn) skipBtn.disabled = true;
  };
  retryBtn.onclick = () => {
    disableBoth();
    retryBtn.textContent = '재시도 중...';
    send({ type: 'user_input', content: 'retry' });
  };
  if (skipBtn) {
    skipBtn.onclick = () => {
      disableBoth();
      skipBtn.textContent = '건너뜀...';
      send({ type: 'user_input', content: 'skip' });
    };
  }

  retryRow.appendChild(retryBtn);
  if (skipBtn) retryRow.appendChild(skipBtn);
  chatScroll().appendChild(retryRow);
  trimContainer(chatScroll(), MAX_CHAT_NODES);
  scrollBottom(chatScroll());
}

function stripAnsi(text) {
  return text.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '');
}

function appendToolOutput(text, isError = false) {
  const right = rightScroll();
  const last = right.lastElementChild;
  const clean = stripAnsi(text);
  if (last && last.classList.contains('tool-block') && !last.classList.contains('error') && !isError) {
    last.textContent += '\n' + clean;
    trimBlockLines(last);
  } else {
    const div = document.createElement('div');
    div.className = 'tool-block' + (isError ? ' error' : '');
    div.textContent = clean;
    right.appendChild(div);
    trimContainer(right, MAX_TOOL_BLOCKS);
  }
  scrollBottom(right);
}

function appendPlot(filename) {
  const card = document.createElement('div');
  card.className = 'plot-card';

  const img = document.createElement('img');
  // 재생성된 파일을 받도록 캐시 키를 추가한다.
  img.src = `/plots/${filename}?t=${Date.now()}`;
  img.alt = filename;
  img.onclick = () => openLightbox(img.src);

  const label = document.createElement('div');
  label.className = 'plot-label';
  label.textContent = filename;

  card.appendChild(img);
  card.appendChild(label);
  rightScroll().appendChild(card);
  scrollBottom(rightScroll());
}

function clearPanels() {
  chatScroll().innerHTML = '';
  rightScroll().innerHTML = '';
}

function setStatus(text, cls) {
  const pill = document.getElementById('status-pill');
  pill.textContent = text;
  pill.className = cls ? `${cls}` : '';
}

function setAgentButtons(running) {
  ['btn-em', 'btn-calib', 'btn-hv', 'btn-hv-sim', 'btn-pos', 'btn-pos-sim'].forEach(id => {
    const btn = document.getElementById(id);
    btn.disabled = running;
    btn.classList.toggle('active', running && id === 'btn-' + agentIdOf(activeAgent));
  });
  document.getElementById('stop-btn').style.display = running ? 'inline-block' : 'none';
}

function agentIdOf(name) {
  return { em_scan: 'em', calib_scan: 'calib', hv_equalization: 'hv', hv_equalization_sim: 'hv-sim', position_scan: 'pos', position_scan_sim: 'pos-sim' }[name] || '';
}

function chatScroll()  { return document.getElementById('chat-scroll'); }
function rightScroll() { return document.getElementById('right-scroll'); }
function scrollBottom(el) { _scrollTargets.add(el); }

/* 별도 요청 결과 팝업. */
function adhocScroll() { return document.getElementById('adhoc-scroll'); }

function openAdhoc(clearContent = false) {
  const overlay = document.getElementById('adhoc-overlay');
  if (_pendingAdhocClear) {
    adhocScroll().innerHTML = '';
    _pendingAdhocClear = false;
  }
  if (!overlay.classList.contains('open')) {
    if (clearContent) adhocScroll().innerHTML = '';
    overlay.classList.add('open');
  }
}

function closeAdhoc() {
  document.getElementById('adhoc-overlay').classList.remove('open');
}

function adhocAppendToolOutput(text, isError = false) {
  openAdhoc();
  const scroll = adhocScroll();
  const last = scroll.lastElementChild;
  const clean = stripAnsi(text);
  if (last && last.classList.contains('adhoc-tool-block') && !last.classList.contains('error') && !isError) {
    last.textContent += '\n' + clean;
    trimBlockLines(last);
  } else {
    const div = document.createElement('div');
    div.className = 'adhoc-tool-block' + (isError ? ' error' : '');
    div.textContent = clean;
    scroll.appendChild(div);
    trimContainer(scroll, MAX_ADHOC_NODES);
  }
  scroll.scrollTop = scroll.scrollHeight;
}

function adhocAppendHtml(html) {
  openAdhoc();
  const scroll = adhocScroll();
  const div = document.createElement('div');
  div.className = 'adhoc-tool-block';
  div.innerHTML = html;
  scroll.appendChild(div);
  scroll.scrollTop = scroll.scrollHeight;
}

function appendHtml(html) {
  const right = rightScroll();
  const div = document.createElement('div');
  div.className = 'tool-block';
  div.innerHTML = html;
  right.appendChild(div);
  scrollBottom(right);
}

function adhocShowConfirm(preview, _tool, scenarioRunning = false) {
  openAdhoc();
  const scroll = adhocScroll();

  // 기존 확인 카드를 제거한다.
  scroll.querySelectorAll('.adhoc-confirm-card').forEach(el => el.remove());

  const card = document.createElement('div');
  card.className = 'adhoc-confirm-card';

  const title = document.createElement('div');
  title.className = 'adhoc-confirm-title';
  title.textContent = '⚠️ 확인이 필요합니다';
  card.appendChild(title);

  const body = document.createElement('div');
  body.className = 'adhoc-confirm-body';
  body.textContent = preview;
  card.appendChild(body);

  const btnRow = document.createElement('div');
  btnRow.className = 'adhoc-confirm-btns';

  const yesBtn = document.createElement('button');
  yesBtn.className = 'adhoc-confirm-yes';
  yesBtn.textContent = '✔ 확인';
  yesBtn.onclick = () => {
    send({ type: 'adhoc_confirm', confirmed: true });
    card.remove();
    if (!scenarioRunning) closeAdhoc();
  };

  const noBtn = document.createElement('button');
  noBtn.className = 'adhoc-confirm-no';
  noBtn.textContent = '✕ 취소';
  noBtn.onclick = () => {
    send({ type: 'adhoc_confirm', confirmed: false });
    card.remove();
    if (!scenarioRunning) closeAdhoc();
  };

  btnRow.appendChild(yesBtn);
  btnRow.appendChild(noBtn);
  card.appendChild(btnRow);

  scroll.appendChild(card);
  scroll.scrollTop = scroll.scrollHeight;
}

function adhocAppendLink(url, label) {
  openAdhoc();
  const scroll = adhocScroll();

  const wrap = document.createElement('div');
  wrap.className = 'adhoc-tool-block';

  const a = document.createElement('a');
  a.href = url;
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = '🔗 ' + label;
  a.style.cssText = 'color:#4f8ef7;text-decoration:underline;cursor:pointer;font-size:13px;';

  wrap.appendChild(a);
  scroll.appendChild(wrap);
  scroll.scrollTop = scroll.scrollHeight;
}

function adhocAppendPlot(filename) {
  openAdhoc();
  const scroll = adhocScroll();

  const card = document.createElement('div');
  card.className = 'adhoc-plot-card';

  const img = document.createElement('img');
  img.src = `/plots/${filename}?t=${Date.now()}`;
  img.alt = filename;
  img.onclick = () => openLightbox(img.src);

  const label = document.createElement('div');
  label.className = 'plot-label';
  label.textContent = filename;

  card.appendChild(img);
  card.appendChild(label);
  scroll.appendChild(card);
  scroll.scrollTop = scroll.scrollHeight;
}

function adhocDrawDqmCanvases(base_prefix, canvases) {
  openAdhoc();
  const scroll = adhocScroll();

  // 플롯 제목.
  const header = document.createElement('div');
  header.className = 'adhoc-tool-block';
  header.textContent = `DQM: ${base_prefix} (${canvases.length} canvas${canvases.length !== 1 ? 'es' : ''})`;
  scroll.appendChild(header);

  // 플롯 격자.
  const grid = document.createElement('div');
  grid.className = 'adhoc-dqm-grid';
  scroll.appendChild(grid);

  canvases.forEach(canvas => {
    const cell = document.createElement('div');
    cell.className = 'adhoc-dqm-cell';

    const label = document.createElement('div');
    label.className = 'adhoc-dqm-label';
    label.textContent = canvas;
    cell.appendChild(label);

    const drawEl = document.createElement('div');
    drawEl.className = 'adhoc-dqm-draw';
    drawEl.id = `adhoc-dqm-draw-${canvas}`;
    cell.appendChild(drawEl);

    grid.appendChild(cell);

    // ROOT 번들에서 선택한 캔버스를 읽는다.
    (async () => {
      try {
        const jsroot = _getJSROOT();
        const file = await jsroot.openFile(`/dqm-output/${base_prefix}.root?t=${Date.now()}`);
        const obj = await file.readObject(canvas);
        if (!obj) { drawEl.textContent = 'No data'; return; }
        await jsroot.draw(drawEl, obj, '');
      } catch (e) {
        drawEl.textContent = `ERR: ${e.message || e}`;
        drawEl.style.cssText = 'color:red;font-size:11px;padding:8px;white-space:pre-wrap;';
      }
    })();
  });

  scroll.scrollTop = scroll.scrollHeight;
}

/* 이미지 확대 보기. */
function openLightbox(src) {
  document.getElementById('lightbox-img').src = src;
  document.getElementById('lightbox').classList.add('open');
}
function closeLightbox() {
  document.getElementById('lightbox').classList.remove('open');
}
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    // 확대 보기를 먼저 닫고 결과 팝업을 닫는다.
    if (document.getElementById('lightbox').classList.contains('open')) {
      closeLightbox();
    } else if (document.getElementById('adhoc-overlay').classList.contains('open')) {
      closeAdhoc();
    }
  }
});

/* 서버의 faster-whisper를 사용하는 음성 입력. */
let mediaRecorder = null;
let voiceActive = false;

function toggleVoice() {
  voiceActive ? stopVoice() : startVoice();
}

async function startVoice() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    alert('마이크 권한이 필요합니다.');
    return;
  }

  const chunks = [];
  const mime = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
    ? 'audio/webm;codecs=opus' : 'audio/webm';

  mediaRecorder = new MediaRecorder(stream, { mimeType: mime });
  mediaRecorder.ondataavailable = e => { if (e.data.size > 0) chunks.push(e.data); };

  mediaRecorder.onstop = async () => {
    stream.getTracks().forEach(t => t.stop());
    const blob = new Blob(chunks, { type: mime });
    const btn  = document.getElementById('mic-btn');
    btn.textContent = '⌛';
    btn.disabled = true;

    try {
      const form = new FormData();
      form.append('audio', blob, 'audio.webm');
      const res  = await fetch('/transcribe', { method: 'POST', body: form });
      const json = await res.json();
      if (json.text) {
        document.getElementById('chat-input').value = json.text;
        sendText();
      }
    } catch (err) {
      console.error('Whisper error:', err);
    } finally {
      btn.textContent = '🎤';
      btn.disabled = false;
    }
  };

  mediaRecorder.start();
  voiceActive = true;
  const btn = document.getElementById('mic-btn');
  btn.textContent = '⏹';
  btn.classList.add('mic-active');
}

function stopVoice() {
  voiceActive = false;
  document.getElementById('mic-btn').classList.remove('mic-active');
  if (mediaRecorder && mediaRecorder.state !== 'inactive') {
    mediaRecorder.stop();   // 녹음 종료 후 변환을 시작한다.
    mediaRecorder = null;
  }
}

/* DAQ 완료 알림음. */
// 지원 파일이 없으면 합성 알림음을 사용한다.
const _DAQ_SOUND_SOURCES = [
  '/static/audio/daq_complete.mp3',
  '/static/audio/daq_complete.wav',
  '/static/audio/daq_complete.ogg',
  '/static/audio/daq_complete.m4a',
];

// 빠른 재생을 위해 지원 음원을 순서대로 미리 불러온다.
const _daqAudio = new Audio(_DAQ_SOUND_SOURCES[0]);
_daqAudio.preload = 'auto';

// Web Audio API 합성 알림음.
let _audioCtx = null;
function _getAudioCtx() {
  if (!_audioCtx)
    _audioCtx = new (window.AudioContext || /** @type {any} */(window).webkitAudioContext)();
  return _audioCtx;
}
// 첫 사용자 동작에서 브라우저의 오디오 재생 권한을 활성화한다.
function _unlockAudio() {
  const ctx = _getAudioCtx();
  if (ctx.state !== 'running') ctx.resume().catch(() => {});
  _daqAudio.play().then(() => { _daqAudio.pause(); _daqAudio.currentTime = 0; }).catch(() => {});
  document.removeEventListener('click',   _unlockAudio);
  document.removeEventListener('keydown', _unlockAudio);
}
document.addEventListener('click',   _unlockAudio);
document.addEventListener('keydown', _unlockAudio);

function _playChimeFallback() {
  try {
    const ctx = _getAudioCtx();
    const _play = () => {
      try {
        [523.25, 659.25, 783.99].forEach((freq, i) => {
          const osc  = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.connect(gain); gain.connect(ctx.destination);
          osc.type = 'sine'; osc.frequency.value = freq;
          const t = ctx.currentTime + i * 0.15;
          gain.gain.setValueAtTime(0, t);
          gain.gain.linearRampToValueAtTime(0.28, t + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.001, t + 0.45);
          osc.start(t); osc.stop(t + 0.45);
        });
        console.log('[autoTB] DAQ chime played');
      } catch (e) { console.warn('[autoTB] Chime play error:', e); }
    };
    if (ctx.state === 'running') {
      _play();
    } else {
      ctx.resume().then(_play).catch(err => console.warn('[autoTB] Chime resume failed:', err));
    }
  } catch (err) {
    console.warn('[autoTB] Chime failed:', err);
  }
}

// 알림음 설정을 localStorage에 저장한다.
let _soundEnabled = localStorage.getItem('daqSoundEnabled') !== 'false';

function _updateSoundBtn() {
  const btn = document.getElementById('sound-btn');
  if (btn) btn.textContent = _soundEnabled ? '🔔' : '🔕';
}

function toggleSound() {
  _soundEnabled = !_soundEnabled;
  localStorage.setItem('daqSoundEnabled', _soundEnabled);
  _updateSoundBtn();
}

function playDaqCompleteSound() {
  if (!_soundEnabled) return;
  // 미리 불러온 단일 오디오 요소를 재사용한다.
  _daqAudio.currentTime = 0;
  _daqAudio.play()
    .then(() => console.log('[autoTB] DAQ sound (mp3) played'))
    .catch(err => {
      console.warn('[autoTB] MP3 play failed, falling back to chime:', err.message);
      _playChimeFallback();
    });
}

/* DQM 실시간 대시보드. */

let dqmRun = null;
let dqmBasePrefix = null;
let dqmCells = [];                 // 현재 표시 중인 캔버스 이름.
const dqmDrawnObjects = new Map(); // 캔버스별 JSROOT painter.
const dqmDrawing = new Set();      // 그리는 중인 캔버스.
function _getJSROOT() {
  // script 태그로 로드된 JSROOT 전역 객체를 반환한다.
  if (!window.JSROOT) throw new Error('JSROOT not loaded');
  return window.JSROOT;
}

// 실시간 캔버스가 공유하는 ROOT 파일 핸들을 캐시한다.
let _dqmFilePromise = null;
function _openDqmRoot(bust) {
  if (!dqmBasePrefix) return Promise.reject(new Error('no basePrefix'));
  if (bust || !_dqmFilePromise) {
    const url = `/dqm-output/${dqmBasePrefix}.root?t=${Date.now()}`;
    // 파일 열기에 실패하면 다음 호출에서 다시 시도한다.
    _dqmFilePromise = _getJSROOT().openFile(url).catch(err => {
      _dqmFilePromise = null;
      throw err;
    });
  }
  return _dqmFilePromise;
}

function dqmCellsContainer() { return document.getElementById('dqm-cells'); }
function dqmTitleEl()        { return document.getElementById('dqm-title'); }

function _emptyDqmCell(message) {
  const div = document.createElement('div');
  div.className = 'dqm-cell empty';
  div.textContent = message;
  return div;
}

function dqmLiveStart(msg) {
  dqmRun = msg.run_number;
  dqmBasePrefix = msg.base_prefix;
  dqmCells = (msg.cells || []).slice();
  dqmDrawnObjects.clear();
  dqmDrawing.clear();
  _dqmFilePromise = null;   // 새 세션에서는 파일 캐시를 비운다.

  dqmTitleEl().textContent =
    `DQM Live · Run ${dqmRun} · ${msg.method || ''} · ●LIVE`;

  const cont = dqmCellsContainer();
  cont.innerHTML = '';
  if (dqmCells.length === 0) {
    cont.appendChild(_emptyDqmCell('manifest에 cell이 정의되지 않음'));
    return;
  }
  dqmCells.forEach(addDqmCell);
}

function addDqmCell(canvas) {
  const cont = dqmCellsContainer();
  // 중복 캔버스를 제거한다.
  if (cont.querySelector(`[data-canvas="${CSS.escape(canvas)}"]`)) return;

  const card = document.createElement('div');
  card.className = 'dqm-cell';
  card.dataset.canvas = canvas;

  const label = document.createElement('div');
  label.className = 'dqm-cell-label';
  label.textContent = canvas;
  card.appendChild(label);

  const removeBtn = document.createElement('button');
  removeBtn.className = 'dqm-cell-remove';
  removeBtn.textContent = '×';
  removeBtn.title = '제거';
  removeBtn.onclick = (e) => {
    e.stopPropagation();
    dqmCells = dqmCells.filter(c => c !== canvas);
    dqmDrawnObjects.delete(canvas);
    card.remove();
    if (dqmCellsContainer().children.length === 0) {
      dqmCellsContainer().appendChild(_emptyDqmCell('표시할 캔버스가 없습니다 · "+ 캔버스" 로 추가'));
    }
  };
  card.appendChild(removeBtn);

  const draw = document.createElement('div');
  draw.className = 'dqm-cell-draw';
  draw.id = `dqm-draw-${canvas}`;
  card.appendChild(draw);

  card.onclick = () => openDqmModal(canvas);

  // 빈 상태 안내를 제거한다.
  const empty = cont.querySelector('.dqm-cell.empty');
  if (empty) empty.remove();

  cont.appendChild(card);

  // 캔버스의 초기 내용을 그린다.
  _drawCellFromServer(canvas);
}

async function _drawCellFromServer(canvas) {
  if (dqmDrawing.has(canvas)) return;   // 동시 그리기를 막는다.
  if (!dqmBasePrefix) { console.warn('[DQM] no basePrefix'); return; }
  const drawEl = document.getElementById(`dqm-draw-${canvas}`);
  if (!drawEl) { console.warn('[DQM] no drawEl for', canvas); return; }
  dqmDrawing.add(canvas);
  try {
    const file = await _openDqmRoot(false);
    const obj = await file.readObject(canvas);
    if (!obj) { console.warn('[DQM] canvas not in file yet:', canvas); return; }
    const jsroot = _getJSROOT();
    await jsroot.cleanup(drawEl);
    await jsroot.draw(drawEl, obj, '');
    dqmDrawnObjects.set(canvas, obj);
  } catch (e) {
    console.error('[DQM] draw failed', canvas, e);
    drawEl.textContent = `ERR: ${e.message || e}`;
    drawEl.style.cssText = 'color:red;font-size:11px;padding:8px;white-space:pre-wrap;';
  } finally {
    dqmDrawing.delete(canvas);
  }
}

async function dqmRefresh(msg) {
  // 갱신된 ROOT 파일을 다시 열고 모든 캔버스를 그린다.
  if (!dqmBasePrefix) return;
  try {
    await _openDqmRoot(true);
  } catch (e) {
    console.warn('[DQM] refresh reopen failed', e);
    return;
  }
  dqmCells.forEach(c => _drawCellFromServer(c));
}

function dqmLiveEnd(msg) {
  dqmTitleEl().textContent = `DQM · Run ${msg.run_number} · 종료`;
  // 종료 후에도 마지막 캔버스를 유지한다.
}

/* DQM 캔버스 확대 보기. */
async function openDqmModal(canvas) {
  if (!dqmBasePrefix) return;
  document.getElementById('dqm-modal-title').textContent = canvas;
  document.getElementById('dqm-modal').classList.add('open');

  const modalEl = document.getElementById('dqm-modal-draw');
  modalEl.innerHTML = '';

  try {
    const file = await _openDqmRoot(false);
    const obj = await file.readObject(canvas);
    if (!obj) {
      modalEl.textContent = '아직 데이터가 생성되지 않았습니다.';
      return;
    }
    const jsroot = _getJSROOT();
    await jsroot.draw(modalEl, obj, '');
  } catch (e) {
    console.error('[DQM] modal draw failed', e);
    modalEl.textContent = '플롯 렌더링 실패: ' + (e.message || e);
    modalEl.style.cssText = 'color:red;font-size:13px;padding:16px;white-space:pre-wrap;';
  }
}

function closeDqmModal() {
  document.getElementById('dqm-modal').classList.remove('open');
  document.getElementById('dqm-modal-draw').innerHTML = '';
}

/* DQM 캔버스 추가 선택기. */
async function openDqmPicker() {
  if (!dqmRun) {
    alert('DQM live 세션이 아직 시작되지 않았습니다.');
    return;
  }
  document.getElementById('dqm-picker').classList.add('open');
  const list = document.getElementById('dqm-picker-list');
  list.innerHTML = '<div class="dqm-picker-item disabled">불러오는 중…</div>';
  try {
    // ROOT 번들의 TKey에서 캔버스 목록을 읽는다.
    const file = await _openDqmRoot(true);
    const keys = (file.fKeys || []).filter(k => {
      const cls = k.fClassName || '';
      return cls !== 'TList' && cls.indexOf('StreamerInfo') < 0;
    });
    list.innerHTML = '';
    if (!keys.length) {
      list.innerHTML = '<div class="dqm-picker-item disabled">아직 생성된 캔버스가 없습니다.</div>';
      return;
    }
    keys.forEach(k => {
      const name = k.fName;
      const div = document.createElement('div');
      div.className = 'dqm-picker-item';
      const already = dqmCells.includes(name);
      if (already) div.classList.add('disabled');
      div.innerHTML = `${name}` +
        `<div class="meta">${k.fClassName || ''}${already ? ' · 추가됨' : ''}</div>`;
      if (!already) {
        div.onclick = () => {
          dqmCells.push(name);
          addDqmCell(name);
          closeDqmPicker();
        };
      }
      list.appendChild(div);
    });
  } catch (e) {
    list.innerHTML = `<div class="dqm-picker-item disabled">에러: ${e.message}</div>`;
  }
}

function closeDqmPicker() {
  document.getElementById('dqm-picker').classList.remove('open');
}

function openDqmFreeform() {
  const url = dqmRun ? `/dqm/freeform?run=${dqmRun}` : '/dqm/freeform';
  window.open(url, '_blank', 'width=1400,height=900');
}

document.addEventListener('DOMContentLoaded', () => {
  const addBtn = document.getElementById('dqm-add-btn');
  const ffBtn  = document.getElementById('dqm-freeform-btn');
  const hvCheckBtn = document.getElementById('hv-check-btn');
  if (addBtn) addBtn.onclick = openDqmPicker;
  if (ffBtn)  ffBtn.onclick  = openDqmFreeform;
  if (hvCheckBtn) hvCheckBtn.onclick = openHvCheck;

  // 빈 상태 안내를 표시한다.
  const cont = document.getElementById('dqm-cells');
  if (cont && cont.children.length === 0) {
    const div = document.createElement('div');
    div.className = 'dqm-cell empty';
    div.textContent = 'DAQ run이 시작되면 자동으로 표시됩니다';
    cont.appendChild(div);
  }
});

// Escape 키로 DQM 팝업도 닫는다.
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  const modal = document.getElementById('dqm-modal');
  const picker = document.getElementById('dqm-picker');
  if (modal && modal.classList.contains('open')) { closeDqmModal(); return; }
  if (picker && picker.classList.contains('open')) { closeDqmPicker(); return; }
});

/* 10초 간격 모터 위치 조회. */
function _updateMotorBar(text) {
  const bar = document.getElementById('motor-pos-bar');
  if (bar) bar.textContent = 'Motor: ' + text;
}

async function _pollMotorPosition() {
  try {
    const r = await fetch('/api/motor/position');
    const data = await r.json();
    _updateMotorBar(data.ok ? data.position : '읽기 실패');
  } catch (e) {
    _updateMotorBar('오프라인');
  }
}

// 로드 직후 조회하고 10초마다 반복한다.
_pollMotorPosition();
setInterval(_pollMotorPosition, 10000);

/* 채팅 입력의 Enter와 위·아래 키 처리. */
(function () {
  const input = document.getElementById('chat-input');
  if (!input) return;
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      sendText();
      return;
    }
    if (e.key === 'ArrowUp') {
      if (_cmdHistory.length === 0) return;
      e.preventDefault();
      if (_histIdx === -1) _histDraft = input.value;   // 현재 입력을 보관한다.
      _histIdx = Math.min(_histIdx + 1, _cmdHistory.length - 1);
      input.value = _cmdHistory[_histIdx];
      // 커서를 입력 끝으로 옮긴다.
      requestAnimationFrame(() => { input.selectionStart = input.selectionEnd = input.value.length; });
      return;
    }
    if (e.key === 'ArrowDown') {
      if (_histIdx === -1) return;
      e.preventDefault();
      _histIdx -= 1;
      input.value = _histIdx === -1 ? _histDraft : _cmdHistory[_histIdx];
      requestAnimationFrame(() => { input.selectionStart = input.selectionEnd = input.value.length; });
    }
  });
})();

/* 타워 선택기. */
// 행 우선 3×3 배치.
const TOWER_GRID = [
  ['T1','T2','T3'],  // row 0
  ['T4','T5','T6'],  // row 1
  ['T7','T8','T9'],  // row 2
];

// 선택 항목 정렬용 지그재그 순서.
const SERPENTINE_ORDER = [
  ...TOWER_GRID[0],
  ...[...TOWER_GRID[1]].reverse(),
  ...TOWER_GRID[2],
];

let _towerPickerAgent = null;
let _towerPickerMulti = false;
let _towerSelected = new Set();
let _towerDragging = false;
let _towerDragMode = null; // 선택 또는 해제.

const POSITION_AGENTS = ['position_scan', 'position_scan_sim'];
let _posDirection = null;   // 'horizontal' | 'vertical' | 'both'
let _posChannel = null;     // 'C' | 'S'

function openTowerPicker(agentName) {
  _towerPickerAgent = agentName;
  _towerPickerMulti = !['em_scan', 'position_scan', 'position_scan_sim'].includes(agentName);
  _towerSelected.clear();

  const isPos = POSITION_AGENTS.includes(agentName);
  _posDirection = null;
  _posChannel = null;
  const posOpts = document.getElementById('pos-options');
  if (posOpts) posOpts.style.display = isPos ? 'block' : 'none';
  document.querySelectorAll('.pos-opt-btn').forEach(b => b.classList.remove('selected'));

  const hint = document.getElementById('tower-picker-hint');
  hint.textContent = _towerPickerMulti
    ? '클릭 또는 드래그로 여러 타워 선택'
    : (isPos ? '타워·방향·채널을 선택하세요' : '타워 하나를 선택하세요');

  _buildTowerGrid();
  _updateTowerPickerFooter();
  document.getElementById('tower-picker-overlay').classList.add('open');
}

function selectPosOption(kind, value) {
  if (kind === 'direction') _posDirection = value;
  else if (kind === 'channel') _posChannel = value;
  document.querySelectorAll(`.pos-opt-btn[data-kind="${kind}"]`).forEach(b => {
    b.classList.toggle('selected', b.dataset.value === value);
  });
  _updateTowerPickerFooter();
}

function closeTowerPicker() {
  document.getElementById('tower-picker-overlay').classList.remove('open');
  _towerPickerAgent = null;
}

function clearTowerSelection() {
  _towerSelected.clear();
  document.querySelectorAll('.tower-cell').forEach(c => c.classList.remove('selected'));
  _updateTowerPickerFooter();
}

function _buildTowerGrid() {
  const grid = document.getElementById('tower-grid');
  grid.innerHTML = '';

  TOWER_GRID.forEach(row => {
    row.forEach(tower => {
      const cell = document.createElement('div');
      cell.className = 'tower-cell';
      cell.textContent = tower;
      cell.dataset.tower = tower;

      cell.addEventListener('mousedown', e => {
        e.preventDefault();
        _towerDragging = true;
        const isSelected = _towerSelected.has(tower);
        if (!_towerPickerMulti) {
          // 단일 선택은 현재 타워만 토글한다.
          _towerSelected.clear();
          document.querySelectorAll('.tower-cell').forEach(c => c.classList.remove('selected'));
          _towerSelected.add(tower);
          cell.classList.add('selected');
        } else {
          _towerDragMode = isSelected ? 'deselect' : 'select';
          _toggleTowerCell(cell, tower);
        }
        _updateTowerPickerFooter();
      });

      cell.addEventListener('mouseenter', () => {
        if (!_towerDragging || !_towerPickerMulti) return;
        _toggleTowerCell(cell, tower, _towerDragMode);
        _updateTowerPickerFooter();
      });

      grid.appendChild(cell);
    });
  });

  document.addEventListener('mouseup', () => { _towerDragging = false; }, { once: false });
}

function _toggleTowerCell(cell, tower, forcedMode) {
  const mode = forcedMode || (_towerSelected.has(tower) ? 'deselect' : 'select');
  if (mode === 'select') {
    _towerSelected.add(tower);
    cell.classList.add('selected');
  } else {
    _towerSelected.delete(tower);
    cell.classList.remove('selected');
  }
}

function _updateTowerPickerFooter() {
  const n = _towerSelected.size;
  document.getElementById('tower-picker-count').textContent = `${n}개 선택됨`;
  const confirmBtn = document.getElementById('tower-picker-confirm');
  if (POSITION_AGENTS.includes(_towerPickerAgent)) {
    confirmBtn.disabled = !(n === 1 && _posDirection && _posChannel);
  } else if (_towerPickerMulti) {
    confirmBtn.disabled = (n === 0);
  } else {
    confirmBtn.disabled = (n !== 1);
  }
}

function confirmTowerPicker() {
  if (!_towerPickerAgent) return;
  const agentName = _towerPickerAgent;
  closeTowerPicker();

  // 선택한 타워를 지그재그 순서로 정렬한다.
  const selected = Array.from(_towerSelected);
  const ordered = SERPENTINE_ORDER.filter(t => selected.includes(t));

  let params = {};
  if (POSITION_AGENTS.includes(agentName)) {
    params = { tower: ordered[0], direction: _posDirection, channel: _posChannel };
  } else if (agentName === 'em_scan') {
    params = { tower: ordered[0] };
  } else {
    params = { tower_order: ordered };
  }

  _launchAgent(agentName, params);
}

/* 초기화. */
_updateSoundBtn();
connectWS();
