# simple_task_mcp.py
# FastMCP 기반: tasks.list / tasks.peek / tasks.next / tasks.reset / tasks.goto
# Copyright (c) 2024 Simple Task MCP
# MIT License - see LICENSE file for details
# 실행:
#   uv run simple_task_mcp.py     (권장)
#   또는 python simple_task_mcp.py

from __future__ import annotations
import argparse
import json
import logging
import os
import hashlib
from pathlib import Path
from typing import List, Dict, Set

from mcp.server.fastmcp import FastMCP  # 공식 Python SDK의 FastMCP 사용
# 참고: https://modelcontextprotocol.io/quickstart/server

logging.basicConfig(level=logging.INFO)

mcp = FastMCP("simple-task-mcp")  # 서버 이름 (Cursor 설정과 일치)

# ---------- 인자/환경 설정 ----------
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--project-root", default=".", help="프로젝트 루트 디렉토리")
    p.add_argument("--file", default="./.simple/simple_task.txt", help="작업 파일(.txt) - .simple 디렉토리 내에서 찾음")
    p.add_argument("--state", default="./.simple/simple_state.json", help="작업 진행 상태 저장 파일")
    return p.parse_args()

ARGS = parse_args()

# ✅ 프로젝트 루트 설정
PROJECT_ROOT = Path(ARGS.project_root).resolve()
logging.info(f"Using project root: {PROJECT_ROOT}")

# 프로젝트 루트가 존재하는지 확인
if not PROJECT_ROOT.exists():
    logging.error(f"❌ Project root does not exist: {PROJECT_ROOT}")
    exit(1)

# 상대경로를 프로젝트 루트 기준으로 해석
TASKS_PATH = (PROJECT_ROOT / ARGS.file).resolve()
STATE_PATH = (PROJECT_ROOT / ARGS.state).resolve()

# ---------- 상태 로딩/저장 ----------
def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            # list 타입들을 set으로 변환
            if "completed_tasks" in state and isinstance(state["completed_tasks"], list):
                state["completed_tasks"] = set(state["completed_tasks"])
            if "completed_hashes" in state and isinstance(state["completed_hashes"], list):
                state["completed_hashes"] = set(state["completed_hashes"])
            return state
        except Exception:
            pass
    return {"index": 0}

def generate_task_hash(task_content: str) -> str:
    """작업 내용을 기반으로 해시를 생성합니다."""
    return hashlib.md5(task_content.encode('utf-8')).hexdigest()[:8]

def get_current_task_hashes() -> Dict[int, str]:
    """현재 작업 목록의 해시를 반환합니다."""
    if not TASKS_PATH.exists():
        return {}
    
    try:
        raw = TASKS_PATH.read_text(encoding="utf-8")
        lines = raw.split('\n')
        
        task_hashes = {}
        current_task = []
        task_index = 0
        
        for line in lines:
            line = line.rstrip()
            if line.strip() == "":  # 빈 줄
                if current_task:  # 현재 작업이 있으면 저장
                    task_content = '\n'.join(current_task).strip()
                    if not task_content.startswith('#'):
                        task_hashes[task_index] = generate_task_hash(task_content)
                        task_index += 1
                    current_task = []
            else:
                current_task.append(line)
        
        # 마지막 작업이 있으면 추가
        if current_task:
            task_content = '\n'.join(current_task).strip()
            if not task_content.startswith('#'):
                task_hashes[task_index] = generate_task_hash(task_content)
        
        return task_hashes
        
    except Exception as e:
        logging.warning(f"⚠️ 작업 해시 생성 중 오류 발생: {e}")
        return {}

def sync_state_with_tasks() -> dict:
    """작업 목록과 상태를 동기화하여 불일치를 해결합니다."""
    current_state = STATE.copy()
    
    # 현재 작업 해시 가져오기
    current_hashes = get_current_task_hashes()
    
    # 기존 해시 기반 완료 상태가 있으면 사용, 없으면 새로 생성
    if "task_hashes" not in current_state:
        current_state["task_hashes"] = {}
    
    if "completed_hashes" not in current_state:
        current_state["completed_hashes"] = set()
    
    # 해시 기반으로 완료 상태 동기화
    new_completed_tasks = set()
    new_completed_hashes = set()
    
    for task_num, task_hash in current_hashes.items():
        # 이전에 완료된 해시인지 확인
        if task_hash in current_state.get("completed_hashes", set()):
            new_completed_tasks.add(task_num)
            new_completed_hashes.add(task_hash)
    
    # 상태 업데이트
    current_state["completed_tasks"] = new_completed_tasks
    current_state["completed_hashes"] = new_completed_hashes
    current_state["task_hashes"] = current_hashes
    
    # index 범위 조정
    total_tasks = len(current_hashes)
    if current_state.get("index", 0) >= total_tasks:
        current_state["index"] = total_tasks
    
    # 상태 저장
    save_state(current_state)
    
    return current_state

def save_state(state: dict) -> None:
    # set 타입들을 list로 변환하여 JSON 호환 가능하게 함
    state_to_save = state.copy()
    if "completed_tasks" in state_to_save and isinstance(state_to_save["completed_tasks"], set):
        state_to_save["completed_tasks"] = list(state_to_save["completed_tasks"])
    if "completed_hashes" in state_to_save and isinstance(state_to_save["completed_hashes"], set):
        state_to_save["completed_hashes"] = list(state_to_save["completed_hashes"])
    STATE_PATH.write_text(json.dumps(state_to_save, indent=2, ensure_ascii=False), encoding="utf-8")

STATE = load_state()

# ---------- 작업 로딩 ----------
def load_rules() -> str:
    """simple_rule.txt 파일에서 규칙들을 로딩 (선택사항) + 기본 보안 규칙 강제 추가"""
    # 기본 보안 규칙 (무조건 포함)
    base_rules = """# 🚨 기본 보안 규칙 (자동 적용)
# - .simple 폴더와 그 안의 파일들을 절대 삭제하지 마세요
# - simple_task.txt, simple_state.json, simple_rule.txt 등은 보존되어야 합니다
# - 필요하면 다른 방법을 사용하세요 (예: 파일 내용 수정, 새 파일 생성 등)
# - 폴더 구조를 변경하거나 삭제하지 마세요

"""
    
    # 프로젝트 루트에서 .simple 디렉토리 내의 simple_rule.txt 찾기
    try:
        rules_path = PROJECT_ROOT / ".simple/simple_rule.txt"
        if rules_path.exists():
            try:
                user_rules = rules_path.read_text(encoding="utf-8").strip()
                if user_rules:
                    logging.info(f"📋 Loaded user rules from: {rules_path}")
                    # 사용자 규칙 + 기본 보안 규칙 결합
                    return base_rules + user_rules
                else:
                    logging.info(f"ℹ️ User rules file is empty, using base security rules only")
                    return base_rules
            except Exception as e:
                logging.warning(f"⚠️ Failed to load user rules: {e}, using base security rules only")
                return base_rules
        else:
            logging.info(f"ℹ️ No user rules file found at: {rules_path}, using base security rules only")
            return base_rules
    except ValueError as e:
        logging.warning(f"⚠️ Invalid rules path: {e}, using base security rules only")
        return base_rules

def load_tasks_raw() -> List[str]:
    """원본 작업만 로딩 (규칙 제외)"""
    if not TASKS_PATH.exists():
        raise FileNotFoundError(f"Tasks file not found: {TASKS_PATH}")
    
    raw = TASKS_PATH.read_text(encoding="utf-8")
    
    # 빈 줄로 구분하여 작업 로딩
    tasks = []
    current_task = []
    
    for line in raw.split('\n'):
        line = line.rstrip()  # 오른쪽 공백 제거
        
        if line.strip() == "":  # 빈 줄
            if current_task:  # 현재 작업이 있으면 저장
                tasks.append('\n'.join(current_task).strip())
                current_task = []
        else:
            current_task.append(line)
    
    # 마지막 작업이 있으면 추가
    if current_task:
        tasks.append('\n'.join(current_task).strip())
    
    if not tasks:
        raise ValueError(f"No tasks found in {TASKS_PATH}")
    
    return tasks

def load_tasks() -> List[str]:
    """규칙이 포함된 작업 로딩 (실제 작업 실행용)"""
    rules = load_rules()
    raw_tasks = load_tasks_raw()
    
    # 규칙이 있으면 각 작업 앞에 추가
    if rules:
        return [f"{rules}\n\n{task}" for task in raw_tasks]
    else:
        return raw_tasks

def clamp_index(idx: int, n: int) -> int:
    if idx < 0: return 0
    if idx > n: return n
    return idx

# ---------- Tools ----------
@mcp.tool()
def show_task_table() -> str:
    """Show task list in table format - 간략한 표 형태로 할일 목록 표시."""
    steps = load_tasks_raw()  # 원본 작업만 로딩 (규칙 제외) + 자동 동기화
    
    # 동기화된 상태에서 완료된 작업 상태 로딩
    completed_tasks = STATE.get("completed_tasks", set())
    
    # 표 헤더 생성
    table_lines = []
    table_lines.append("| 번호 | 상태 | 할일 내용 |")
    table_lines.append("|------|------|-----------|")
    
    # 각 작업을 표 형태로 변환
    for i, task in enumerate(steps):
        # 첫 번째 줄만 추출 (할일 내용)
        first_line = task.split('\n')[0].strip()
        if first_line.startswith('#'):  # 주석인 경우 건너뛰기
            continue
            
        # 작업 상태에 따른 표시 결정 (단순화: 완료 또는 대기)
        if i in completed_tasks:
            status = "✅"  # 완료
        else:
            status = "[대기]"  # 실행전
            
        # 표 행 추가
        table_lines.append(f"| {i} | {status} | {first_line} |")
    
    return "\n".join(table_lines)



@mcp.tool()
def explain_tasks_detailed() -> str:
    """Explain tasks in detail with summary and full content - 할일을 상세하게 설명하고 요약 정보 제공."""
    steps = load_tasks_raw()  # 원본 작업만 로딩 (규칙 제외)
    
    # 완료된 작업 상태 로딩
    completed_tasks = STATE.get("completed_tasks", set())
    
    # 전체 상태 요약 생성
    total_tasks = len([task for task in steps if not task.strip().startswith('#')])
    completed_count = len(completed_tasks)
    waiting_count = total_tasks - completed_count
    
    detail_lines = []
    detail_lines.append("# 📋 상세 할일 목록\n")
    
    # 요약 정보 추가
    detail_lines.append("## 📊 작업 상태 요약")
    detail_lines.append(f"총 {total_tasks}개 작업")
    
    if completed_count > 0 and waiting_count == 0:
        detail_lines.append("모든 작업이 완료(✅) 상태")
    elif waiting_count > 0 and completed_count == 0:
        detail_lines.append("모든 작업이 대기([대기]) 상태")
    else:
        status_parts = []
        if completed_count > 0:
            status_parts.append(f"{completed_count}개 완료(✅)")
        if waiting_count > 0:
            status_parts.append(f"{waiting_count}개 대기(대기)")
        detail_lines.append(f"혼합 상태: {', '.join(status_parts)}")
    
    detail_lines.append("")
    detail_lines.append("---")
    detail_lines.append("")
    
    for i, task in enumerate(steps):
        # 주석인 경우 건너뛰기
        if task.strip().startswith('#'):
            continue
            
        # 작업 상태에 따른 표시 결정 (단순화: 완료 또는 대기)
        if i in completed_tasks:
            status = "✅"  # 완료
        else:
            status = "대기"  # 실행전
            
        # 작업 번호와 상태 표시
        detail_lines.append(f"## {status} 작업 {i}")
        detail_lines.append("")
        
        # 전체 작업 내용 추가
        detail_lines.append(task)
        detail_lines.append("")
        detail_lines.append("---")
        detail_lines.append("")
    
    return "\n".join(detail_lines)

# # 기존 함수명과의 호환성을 위한 별칭
# @mcp.tool()
# def tasks_list() -> str:
#     """Alias for show_task_table - 기존 호환성 유지."""
#     return show_task_table()

# @mcp.tool()
# def tasks_detail() -> str:
#     """Alias for explain_tasks_detailed - 기존 호환성 유지."""
#     return explain_tasks_detailed()

@mcp.tool()
def tasks_peek() -> str:
    """Show current task without advancing the pointer."""
    steps = load_tasks_raw()  # rule 제외하고 순수한 task만 로딩
    STATE["index"] = clamp_index(STATE.get("index", 0), len(steps))
    if STATE["index"] >= len(steps):
        return "✅ All tasks are done."
    
    task = steps[STATE["index"]]
    current_index = STATE["index"]
    
    # 첫 번째 줄만 추출하여 표시
    first_line = task.split('\n')[0].strip()
    return f"📋 현재 작업 {current_index}:\n\n{first_line}"

@mcp.tool()
def tasks_peek_with_rules() -> str:
    """Show current task with rules included (for actual execution)."""
    steps = load_tasks()  # rule 포함하여 로딩
    STATE["index"] = clamp_index(STATE.get("index", 0), len(steps))
    if STATE["index"] >= len(steps):
        return "✅ All tasks are done."
    
    task = steps[STATE["index"]]
    current_index = STATE["index"]
    
    # 첫 번째 줄만 추출하여 표시 (rule은 포함되어 있음)
    first_line = task.split('\n')[0].strip()
    return f"📋 현재 작업 {current_index} (규칙 포함):\n\n{first_line}"

@mcp.tool()
def show_rules() -> str:
    """Show current rules that apply to all tasks (including automatic security rules)."""
    rules = load_rules()
    if rules:
        return f"📋 현재 적용되는 규칙 (기본 보안 규칙 자동 포함):\n\n{rules}"
    else:
        return "ℹ️ 현재 적용되는 규칙이 없습니다."

@mcp.tool()
def sync_tasks() -> str:
    """작업 목록과 상태를 강제로 동기화합니다."""
    try:
        # 상태 동기화 실행
        global STATE
        STATE = sync_state_with_tasks()
        
        # 현재 작업 목록 로딩
        current_tasks = load_tasks_raw()
        
        # 동기화 결과 요약
        total_tasks = len([task for task in current_tasks if not task.strip().startswith('#')])
        completed_count = len(STATE.get("completed_tasks", set()))
        current_index = STATE.get("index", 0)
        
        sync_summary = f"🔄 작업 목록과 상태 동기화 완료!\n\n"
        sync_summary += f"📊 현재 상태:\n"
        sync_summary += f"- 총 작업 수: {total_tasks}개\n"
        sync_summary += f"- 완료된 작업: {completed_count}개\n"
        sync_summary += f"- 현재 인덱스: {current_index}\n"
        
        # 동기화된 작업 목록 표시
        sync_summary += f"\n📋 동기화된 작업 목록:\n"
        for i, task in enumerate(current_tasks):
            if not task.strip().startswith('#'):
                status = "✅" if i in STATE.get("completed_tasks", set()) else "[대기]"
                first_line = task.split('\n')[0].strip()
                task_hash = STATE.get("task_hashes", {}).get(i, "N/A")
                sync_summary += f"{i}. {status} {first_line} (해시: {task_hash})\n"
        
        return sync_summary
        
    except Exception as e:
        return f"❌ 동기화 중 오류 발생: {e}"

@mcp.tool()
def tasks_next(autoAdvance: bool = True) -> str:
    """Get the next task and advance the pointer."""
    steps = load_tasks_raw()  # rule 제외하고 순수한 task만 로딩
    STATE["index"] = clamp_index(STATE.get("index", 0), len(steps))
    if STATE["index"] >= len(steps):
        return "✅ All tasks are done."
    
    task = steps[STATE["index"]]
    current_index = STATE["index"]
    
    # 현재 작업을 완료 상태로 표시
    if "completed_tasks" not in STATE:
        STATE["completed_tasks"] = set()
    STATE["completed_tasks"].add(current_index)
    
    # 성공/실패와 무관하게 진행시키는 간단한 구현 (autoAdvance는 인터페이스 유지용)
    STATE["index"] += 1
    save_state(STATE)
    
    # 첫 번째 줄만 추출하여 표시
    first_line = task.split('\n')[0].strip()
    return f"✅ 작업 {current_index} 완료 후 다음 작업으로 진행:\n\n{first_line}"

@mcp.tool()
def tasks_next_with_rules(autoAdvance: bool = True) -> str:
    """Get the next task with rules included and advance the pointer."""
    steps = load_tasks()  # rule 포함하여 로딩
    STATE["index"] = clamp_index(STATE.get("index", 0), len(steps))
    if STATE["index"] >= len(steps):
        return "✅ All tasks are done."
    
    task = steps[STATE["index"]]
    current_index = STATE["index"]
    
    # 현재 작업을 완료 상태로 표시
    if "completed_tasks" not in STATE:
        STATE["completed_tasks"] = set()
    STATE["completed_tasks"].add(current_index)
    
    # 성공/실패와 무관하게 진행시키는 간단한 구현 (autoAdvance는 인터페이스 유지용)
    STATE["index"] += 1
    save_state(STATE)
    
    # 첫 번째 줄만 추출하여 표시 (rule은 포함되어 있음)
    first_line = task.split('\n')[0].strip()
    return f"✅ 작업 {current_index} 완료 후 다음 작업으로 진행 (규칙 포함):\n\n{first_line}"

@mcp.tool()
def tasks_reset() -> str:
    """Reset pointer to the first task."""
    STATE["index"] = 0
    save_state(STATE)
    return "Pointer reset to 0."

@mcp.tool()
def tasks_reset_status() -> str:
    """Reset completion status of all tasks."""
    reset_count = 0
    
    if "completed_tasks" in STATE:
        STATE["completed_tasks"].clear()
        reset_count += 1
    
    if reset_count > 0:
        save_state(STATE)
        return "🔄 모든 작업의 상태가 초기화되었습니다. (완료 → 실행전)"
    else:
        return "ℹ️ 초기화할 작업 상태가 없습니다."

@mcp.tool()
def tasks_goto(index: int) -> str:
    """Jump pointer to a specific index (0-based)."""
    steps = load_tasks_raw()
    n = clamp_index(int(index), len(steps))
    STATE["index"] = n
    save_state(STATE)
    return f"Pointer moved to {n}."

@mcp.tool()
def tasks_start(index: int) -> str:
    """Mark a specific task as in progress (deprecated - now just shows task info)."""
    steps = load_tasks_raw()
    n = clamp_index(int(index), len(steps))
    
    # 첫 번째 줄만 추출하여 표시
    task_content = steps[n].split('\n')[0].strip()
    return f"ℹ️ 작업 {n} 정보: {task_content}\n\n💡 실행 중 상태는 더 이상 사용하지 않습니다. 작업을 완료하려면 tasks_complete를 사용하세요."

@mcp.tool()
def tasks_complete(index: int) -> str:
    """Mark a specific task as completed."""
    steps = load_tasks_raw()
    n = clamp_index(int(index), len(steps))
    
    # 완료된 작업 목록 초기화 (없는 경우)
    if "completed_tasks" not in STATE:
        STATE["completed_tasks"] = set()
    
    if "completed_hashes" not in STATE:
        STATE["completed_hashes"] = set()
    
    # 작업 내용을 해시화하여 저장
    task_content = steps[n]
    task_hash = generate_task_hash(task_content)
    
    # 작업 번호와 해시 모두 저장
    STATE["completed_tasks"].add(n)
    STATE["completed_hashes"].add(task_hash)
    
    # 현재 작업 해시도 저장
    if "task_hashes" not in STATE:
        STATE["task_hashes"] = {}
    STATE["task_hashes"][n] = task_hash
    
    save_state(STATE)
    
    # 첫 번째 줄만 추출하여 표시
    first_line = task_content.split('\n')[0].strip()
    return f"✅ 작업 {n} 완료 (해시: {task_hash}): {first_line}"

@mcp.tool()
def tasks_uncomplete(index: int) -> str:
    """Mark a specific task as not completed."""
    steps = load_tasks_raw()
    n = clamp_index(int(index), len(steps))
    
    # 완료된 작업 목록이 있는 경우에만 제거
    if "completed_tasks" in STATE and n in STATE["completed_tasks"]:
        STATE["completed_tasks"].remove(n)
        save_state(STATE)
        
        # 첫 번째 줄만 추출하여 표시
        task_content = steps[n].split('\n')[0].strip()
        return f"⏳ 작업 {n} 미완료로 변경: {task_content}"
    else:
        return f"ℹ️ 작업 {n}은 이미 미완료 상태입니다."

@mcp.tool()
def touch_simple(filename: str = ".simple", content: str = "") -> str:
    """현재 워크스페이스 루트(CWD)에 마커 파일을 생성/덮어쓴다."""
    # 절대 경로나 상위 디렉토리 참조 방지
    if filename.startswith('/') or filename.startswith('..') or '..' in filename:
        return "❌ ERR: filename cannot contain absolute paths or parent directory references"
    
    # .simple 폴더 보존 규칙: 삭제는 막되 생성/수정은 허용
    if filename == ".simple":
        # .simple 폴더 자체는 생성 허용
        target = PROJECT_ROOT / filename
        target.mkdir(parents=True, exist_ok=True)
        return f"📁 .simple directory ensured: {target}"
    
    # .simple 폴더 내부 중요 파일들의 삭제는 경고하지만 수정은 허용
    if filename.startswith(".simple/"):
        protected_files = ['simple_task.txt', 'simple_state.json', 'simple_rule.txt']
        if any(protected in filename for protected in protected_files):
            # 중요 파일이지만 수정/생성은 허용 (삭제만 방지)
            pass
    
    # 프로젝트 루트 내에서만 파일 생성 허용
    target = PROJECT_ROOT / filename
    
    # 보안: 프로젝트 루트 밖으로 나가지 않도록 확인
    try:
        target_resolved = target.resolve()
        if not target_resolved.is_relative_to(PROJECT_ROOT):
            return "❌ ERR: path must be within project root"
    except (ValueError, RuntimeError):
        return "❌ ERR: invalid path"
    
    # 디렉토리인 경우 생성
    if filename.endswith('/'):
        target.mkdir(parents=True, exist_ok=True)
        return f"📁 Created directory: {target}"
    
    # 파일인 경우 생성
    target.write_text(content, encoding="utf-8")
    return f"📝 Created file: {target}"

@mcp.tool()
def tasks_auto(count: int = None) -> str:
    """Automatically execute remaining tasks or specified number of tasks."""
    steps_with_rules = load_tasks()  # rule 포함하여 로딩 (실제 실행용)
    steps_raw = load_tasks_raw()  # rule 제외하고 순수한 task만 로딩 (표시용)
    current_index = STATE.get("index", 0)
    total_tasks = len(steps_raw)
    
    if current_index >= total_tasks:
        return "✅ All tasks are already completed."
    
    # 완료된 작업 목록 초기화 (없는 경우)
    if "completed_tasks" not in STATE:
        STATE["completed_tasks"] = set()
    
    # 남은 작업 수 계산
    remaining_tasks = total_tasks - current_index
    
    # count가 지정되지 않았거나 None이면 모든 남은 작업 수행
    if count is None:
        count = remaining_tasks
    else:
        # count가 정수가 아니면 정수로 변환 시도
        try:
            count = int(count)
        except (ValueError, TypeError):
            count = remaining_tasks
    
    # count가 남은 작업보다 많으면 남은 작업 수로 제한
    if count > remaining_tasks:
        count = remaining_tasks
    
    # count가 0 이하면 오류 반환
    if count <= 0:
        return "❌ 유효하지 않은 작업 수입니다. 양수를 입력하거나 비워두세요."
    
    # 실제 작업 실행 및 결과 수집
    execution_results = []
    tasks_to_execute = []
    
    for i in range(current_index, current_index + count):
        if i < total_tasks:
            # 현재 작업 정보 (표시용)
            first_line = steps_raw[i].split('\n')[0].strip()
            tasks_to_execute.append(f"🚀 [{i}] {first_line}")
            
            # 실제 작업 내용 (rule 포함) - LLM이 실행할 수 있도록 제공
            if i < len(steps_with_rules):
                full_task = steps_with_rules[i]
                execution_results.append(f"\n## 🎯 작업 {i} 실행 준비 완료:\n{full_task}\n")
            
            # 작업을 완료 상태로 표시
            STATE["completed_tasks"].add(i)
    
    # 상태 업데이트
    STATE["index"] = current_index + count
    save_state(STATE)
    
    # 결과 메시지 생성
    if count == remaining_tasks:
        message = f"🚀 자동으로 모든 남은 작업({count}개)을 준비했습니다:\n\n"
        message += "\n".join(tasks_to_execute)
        message += f"\n\n✅ 총 {count}개 작업 준비 완료! 이제 각 작업을 실행할 수 있습니다."
        if execution_results:
            message += "\n\n" + "="*50 + "\n🔍 실행할 작업 내용 (규칙 포함):\n" + "\n".join(execution_results)
            message += "\n\n💡 각 작업을 실행하려면 위의 내용을 복사하여 Claude에게 전달하세요."
    else:
        message = f"🚀 자동으로 {count}개 작업을 준비했습니다:\n\n"
        message += "\n".join(tasks_to_execute)
        message += f"\n\n📊 진행 상황: {STATE['index']}/{total_tasks} 준비 완료"
        if execution_results:
            message += "\n\n" + "="*50 + "\n🔍 실행할 작업 내용 (규칙 포함):\n" + "\n".join(execution_results)
            message += "\n\n💡 각 작업을 실행하려면 위의 내용을 복사하여 Claude에게 전달하세요."
    
    return message

# ---------- (선택) 리소스: 각 작업을 파일처럼 노출 ----------
# FastMCP는 리소스/작업도 지원하지만, 여기서는 간단히 tools만 구현해도 Cursor/Claude에서 충분히 사용 가능합니다.
# 필요 시 FastMCP의 리소스 API로 mcp.add_resource(...) 형태를 추가하세요.

if __name__ == "__main__":
    try:
        # .simple 디렉토리 자동 생성
        simple_dir = PROJECT_ROOT / ".simple"
        if not simple_dir.exists():
            logging.info(f"📁 Creating .simple directory at: {simple_dir}")
            simple_dir.mkdir(parents=True, exist_ok=True)

        # 기본 simple_task.txt 파일 생성
        task_file = simple_dir / "simple_task.txt"
        if not task_file.exists():
            default_task = "# 작업 목록을 여기에 작성하세요\n# 빈 줄로 작업을 구분합니다\n\n첫 번째 작업을 작성하세요"
            task_file.write_text(default_task, encoding="utf-8")
            logging.info(f"📝 Created default simple_task.txt")

        # 기본 simple_rule.txt 파일 생성
        rule_file = simple_dir / "simple_rule.txt"
        if not rule_file.exists():
            default_rule = "# 공통 규칙을 여기에 작성하세요\n# 예: 코딩 가이드라인, 작업 원칙 등\n# 이 파일은 선택사항입니다"
            rule_file.write_text(default_rule, encoding="utf-8")
            logging.info(f"📋 Created default simple_rule.txt")

        # 파일 존재 여부 확인 (이제는 항상 존재해야 함)
        if not TASKS_PATH.exists():
            logging.error(f"❌ Tasks file not found: {TASKS_PATH}")
            logging.error(f"   Please check if simple_task.txt exists in: {simple_dir}")
            exit(1)
        
        # 테스트용 작업 로딩 (rule 제외)
        test_tasks = load_tasks_raw()
        logging.info(f"✅ Loaded {len(test_tasks)} tasks successfully")
        
        # 초기 상태 파일 생성 확인
        if not STATE_PATH.exists():
            logging.info(f"📝 Creating initial state file: {STATE_PATH}")
            save_state(STATE)
        
        logging.info(f"🚀 simpletask-mcp running. file={TASKS_PATH} state={STATE_PATH}")
        # STDIO 전송으로 실행 (Claude·Cursor 등 호스트에서 연결)
        mcp.run(transport="stdio")
    except Exception as e:
        logging.error(f"❌ Failed to start MCP server: {e}")
        exit(1)
