import eel
import os
import json
import sqlite3
from openai import OpenAI
import threading
import time
from dotenv import load_dotenv
from prompts import SYSTEM_PROMPTS
from agents import GeneratorAgent, CodingAgent, ReviewerAgent

# Load environment variables
load_dotenv()

# Configure OpenAI
api_key = os.getenv("OPENAI_API_KEY", "no-key-required")
base_url = os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:8073/v1")
model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")

client = OpenAI(
    api_key=api_key,
    base_url=base_url
)

# SQLite Setup
DB_FILE = "ralphboard.db"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            working_dir TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER,
            title TEXT NOT NULL,
            description TEXT,
            success_criteria TEXT,
            is_inprogress INTEGER DEFAULT 0,
            is_review INTEGER DEFAULT 0,
            is_complete INTEGER DEFAULT 0,
            is_failed INTEGER DEFAULT 0,
            dependency_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES projects (id),
            FOREIGN KEY (dependency_id) REFERENCES tasks (id)
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            role TEXT,
            system_prompt_key TEXT,
            status TEXT DEFAULT 'Idle',
            show_window INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    try: cursor.execute('ALTER TABLE projects ADD COLUMN status TEXT DEFAULT "active"')
    except: pass
    try: cursor.execute('ALTER TABLE tasks ADD COLUMN description TEXT')
    except: pass
    try: cursor.execute('ALTER TABLE tasks ADD COLUMN success_criteria TEXT')
    except: pass
    try: cursor.execute('ALTER TABLE tasks ADD COLUMN is_failed INTEGER DEFAULT 0')
    except: pass
    try: cursor.execute('ALTER TABLE agents ADD COLUMN show_window INTEGER DEFAULT 0')
    except: pass
    try: cursor.execute('ALTER TABLE agents ADD COLUMN is_active INTEGER DEFAULT 0')
    except: pass
    try: cursor.execute('ALTER TABLE agents ADD COLUMN target_queues TEXT')
    except: pass
    try: cursor.execute('ALTER TABLE tasks ADD COLUMN review_count INTEGER DEFAULT 0')
    except: pass
    conn.commit()
    conn.close()

init_db()

@eel.expose
def get_board_data():
    conn = get_db()
    cursor = conn.cursor()
    
    # Get all tasks with project names and dependency info, filtering out completed projects
    cursor.execute('''
        SELECT t.*, p.name as project_name, p.working_dir,
               dt.title as dependency_title, dt.is_complete as dep_is_complete
        FROM tasks t 
        JOIN projects p ON t.project_id = p.id
        LEFT JOIN tasks dt ON t.dependency_id = dt.id
        WHERE p.status != 'completed'
    ''')
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    # Calculate statuses
    tasks = []
    for t in rows:
        status = 'todo'
        
        # Check dependencies
        if t['dependency_id'] and not t['dep_is_complete']:
            status = 'backlog'
            
        # Overrides (Order: inprogress, review, complete)
        # User said "override eachother in that order"
        # Often this means the LAST one takes precedence
        if t['is_inprogress']: status = 'inprogress'
        if t['is_failed']: status = 'triage'
        if t['is_review']: status = 'review'
        if t['is_complete']: status = 'complete'
        
        t['status'] = status
        tasks.append(t)
        
    return {"tasks": tasks}

@eel.expose
def get_projects():
    conn = get_db()
    cursor = conn.cursor()
    
    # Get projects with stats
    cursor.execute('''
        SELECT p.*,
               COUNT(t.id) as total_tasks,
               SUM(CASE WHEN t.is_complete = 1 THEN 1 ELSE 0 END) as completed_tasks
        FROM projects p
        LEFT JOIN tasks t ON p.id = t.project_id
        GROUP BY p.id
        ORDER BY p.created_at DESC
    ''')
    
    projects = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return projects

@eel.expose
def update_project(project_id, name, description, working_dir, status):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE projects
        SET name = ?, description = ?, working_dir = ?, status = ?
        WHERE id = ?
    ''', (name, description, working_dir, status, project_id))
    conn.commit()
    conn.close()
    return True

@eel.expose
def delete_project(project_id):
    conn = get_db()
    cursor = conn.cursor()
    # Delete tasks first (foreign key might cascade but let's be safe)
    cursor.execute('DELETE FROM tasks WHERE project_id = ?', (project_id,))
    cursor.execute('DELETE FROM projects WHERE id = ?', (project_id,))
    conn.commit()
    conn.close()
    return True

def check_and_update_project_completion(project_id):
    if not project_id: return
    
    conn = get_db()
    cursor = conn.cursor()
    
    # Check if ANY task is incomplete
    cursor.execute('SELECT COUNT(*) FROM tasks WHERE project_id = ? AND is_complete = 0', (project_id,))
    incomplete_count = cursor.fetchone()[0]
    
    new_status = 'active'
    if incomplete_count == 0:
        # Check if there are ANY tasks at all (don't autocomplete empty projects?)
        cursor.execute('SELECT COUNT(*) FROM tasks WHERE project_id = ?', (project_id,))
        total = cursor.fetchone()[0]
        if total > 0:
            new_status = 'completed'
            
    # Update project status
    # We only update if it changed to avoid redundant writes/logs, though SQL handles it fine.
    # But strictly: If all complete -> Completed. If Any incomplete -> Active.
    cursor.execute('UPDATE projects SET status = ? WHERE id = ?', (new_status, project_id))
    conn.commit()
    conn.close()

@eel.expose
def update_task_state_from_drag(task_id, new_status):
    conn = get_db()
    cursor = conn.cursor()
    
    # Get project_id for auto-complete check
    cursor.execute('SELECT project_id FROM tasks WHERE id = ?', (task_id,))
    row = cursor.fetchone()
    project_id = row['project_id'] if row else None

    # Reset all overrides
    cursor.execute('''
        UPDATE tasks 
        SET is_inprogress = 0, is_review = 0, is_complete = 0, is_failed = 0
        WHERE id = ?
    ''', (task_id,))
    
    # If moving to review, maybe reset review count? Or keep it? keeping it is safer for history.
    # If explicitly dragging, we assume user overrides state.
    
    # Set the appropriate override
    if new_status == 'inprogress':
        cursor.execute('UPDATE tasks SET is_inprogress = 1 WHERE id = ?', (task_id,))
    elif new_status == 'review':
        cursor.execute('UPDATE tasks SET is_review = 1 WHERE id = ?', (task_id,))
    elif new_status == 'complete':
        cursor.execute('UPDATE tasks SET is_complete = 1 WHERE id = ?', (task_id,))
    elif new_status == 'triage':
        cursor.execute('UPDATE tasks SET is_failed = 1 WHERE id = ?', (task_id,))
        
    conn.commit()
    conn.close()
    
    # Auto-complete/activate project
    if project_id:
        check_and_update_project_completion(project_id)
        
    return True

@eel.expose
def update_task_details(task_id, title, description, success_criteria, dependency_id, is_inprogress, is_review, is_complete, is_failed, review_count):
    conn = get_db()
    cursor = conn.cursor()
    
    # Get project_id for auto-complete check
    cursor.execute('SELECT project_id FROM tasks WHERE id = ?', (task_id,))
    row = cursor.fetchone()
    project_id = row['project_id'] if row else None
    
    cursor.execute('''
        UPDATE tasks 
        SET title = ?, description = ?, success_criteria = ?, dependency_id = ?, 
            is_inprogress = ?, is_review = ?, is_complete = ?, is_failed = ?, review_count = ?
        WHERE id = ?
    ''', (title, description, success_criteria, dependency_id if dependency_id else None, 
          1 if is_inprogress else 0, 1 if is_review else 0, 1 if is_complete else 0, 1 if is_failed else 0,
          review_count,
          task_id))
    conn.commit()
    conn.close()
    
    # Auto-complete/activate project
    if project_id:
        check_and_update_project_completion(project_id)

    return True

@eel.expose
def create_task(project_id, title, description="", success_criteria="", expand_with_ai=False):
    """
    Create a new task manually. Optionally expand with AI to generate subtasks.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Validate project exists
        cursor.execute('SELECT id, working_dir FROM projects WHERE id = ?', (project_id,))
        project = cursor.fetchone()
        if not project:
            conn.close()
            return {"success": False, "message": "Project not found"}
        
        working_dir = project['working_dir']
        
        # Create the main task
        cursor.execute('''
            INSERT INTO tasks (project_id, title, description, success_criteria)
            VALUES (?, ?, ?, ?)
        ''', (project_id, title, description, success_criteria))
        
        main_task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        # If AI expansion requested, generate subtasks
        if expand_with_ai and description:
            result = expand_task_with_ai(main_task_id, description, working_dir)
            if result.get("success"):
                return {"success": True, "task_id": main_task_id, "subtasks_created": len(result.get("subtasks", []))}
            else:
                # Main task still created, just expansion failed
                return {"success": True, "task_id": main_task_id, "message": "Task created but AI expansion failed"}
        
        return {"success": True, "task_id": main_task_id}
        
    except Exception as e:
        print(f"Error creating task: {e}")
        return {"success": False, "message": str(e)}

@eel.expose
def expand_task_with_ai(task_id, description, working_dir):
    """
    Use AI to analyze a task description and generate related subtasks.
    """
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # Get the main task
        cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
        main_task = dict(cursor.fetchone())
        
        # Use GeneratorAgent with a specialized prompt
        agent = GeneratorAgent("TaskExpander", SYSTEM_PROMPTS["task_generator"])
        
        expansion_prompt = f"""Analyze this task and break it down into concrete subtasks:

Task Title: {main_task['title']}
Description: {description}
Success Criteria: {main_task.get('success_criteria', 'N/A')}

Generate 3-7 specific subtasks that would be needed to complete this main task. Each subtask should be actionable and have clear success criteria."""
        
        # Generate subtasks
        response_format = {"type": "json_object"}
        system_msg = agent.system_prompt + "\nWrap your response in a json object with a 'tasks' key containing an array of subtasks."
        
        original_prompt = agent.system_prompt
        agent.system_prompt = system_msg
        result = agent.chat(expansion_prompt, response_format)
        agent.system_prompt = original_prompt
        
        if not result:
            conn.close()
            return {"success": False, "message": "AI generation failed"}
        
        data = json.loads(result)
        subtasks = data.get("tasks", [])
        
        # Create subtasks with dependency on main task
        created_subtasks = []
        for subtask_data in subtasks:
            cursor.execute('''
                INSERT INTO tasks (project_id, title, description, success_criteria, dependency_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                main_task['project_id'],
                subtask_data.get('title', 'Untitled Subtask'),
                subtask_data.get('description', ''),
                subtask_data.get('success_criteria', ''),
                task_id  # All subtasks depend on the main task
            ))
            created_subtasks.append(cursor.lastrowid)
        
        conn.commit()
        conn.close()
        
        return {"success": True, "subtasks": created_subtasks}
        
    except Exception as e:
        print(f"Error expanding task with AI: {e}")
        return {"success": False, "message": str(e)}

@eel.expose
def generate_project_tasks(project_title, description, working_dir):
    try:
        # Use the GeneratorAgent automatically
        agent = GeneratorAgent("AutoGenerator", SYSTEM_PROMPTS["task_generator"])
        data = agent.generate_tasks(project_title, description, working_dir)
        
        if not data:
            return False
            
        task_data = data.get("tasks", [])
        
        # Save to DB
        conn = get_db()
        cursor = conn.cursor()
        
        # 1. Create Project
        cursor.execute('INSERT INTO projects (name, description, working_dir) VALUES (?, ?, ?)', 
                       (project_title, description, working_dir))
        project_id = cursor.lastrowid
        
        # 2. Create Tasks (First Pass: Create basic records)
        temp_id_to_real_id = {}
        batch_tasks = []
        for i, t in enumerate(task_data):
            cursor.execute('''
                INSERT INTO tasks (project_id, title, description, success_criteria) 
                VALUES (?, ?, ?, ?)
            ''', (project_id, t['title'], t.get('description'), t.get('success_criteria')))
            real_id = cursor.lastrowid
            temp_id_to_real_id[i] = real_id
            batch_tasks.append({**t, "id": real_id})
            
        # 3. Update Dependencies
        for i, t in enumerate(batch_tasks):
            dep_idx = t.get("dependency_index")
            if dep_idx is not None and dep_idx in temp_id_to_real_id:
                dep_real_id = temp_id_to_real_id[dep_idx]
                cursor.execute('UPDATE tasks SET dependency_id = ? WHERE id = ?', (dep_real_id, t["id"]))
            
        conn.commit()
        conn.close()
        
        return True
    except Exception as e:
        print(f"Error generating tasks: {e}")
        return False

@eel.expose
def get_agents():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM agents ORDER BY created_at DESC')
    rows = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return rows

@eel.expose
def create_agent(name, role, system_prompt_key, show_window):
    conn = get_db()
    cursor = conn.cursor()
    
    # Default queues based on role
    default_queues = "[]"
    if role == "CodingAgent":
        default_queues = '["todo"]'
    elif role == "ReviewerAgent":
        default_queues = '["review"]'
        
    cursor.execute('''
        INSERT INTO agents (name, role, system_prompt_key, show_window, is_active, target_queues) 
        VALUES (?, ?, ?, ?, 0, ?)
    ''', (name, role, system_prompt_key, 1 if show_window else 0, default_queues))
    conn.commit()
    conn.close()
    return True

@eel.expose
def delete_agent(agent_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM agents WHERE id = ?', (agent_id,))
    conn.commit()
    conn.close()
    return True

@eel.expose
def get_available_prompts():
    return list(SYSTEM_PROMPTS.keys())

@eel.expose
def get_agent_classes():
    return ["CodingAgent", "ReviewerAgent", "GeneratorAgent"]

import subprocess
import sys

# ... (existing imports)

def monitor_process(process, task_id, agent_name):
    print(f"DEBUG: Monitoring process for Agent {agent_name} (Task {task_id})")
    process.wait()
    print(f"DEBUG: Process Agent {agent_name} finished. Triggering refresh.")
    # Brief pause to ensure DB lock is released if any
    time.sleep(0.5) 
    
    # Auto-complete check after process finishes (since it might have updated DB externally? 
    # No, external process updates DB directly likely? 
    # If agent_runner.py uses same DB, yes.
    # But wait, agent_runner.py DOES NOT update DB for success/fail?
    # Actually, let's check `run_task_agent` logic. 
    # If running in separate window, `agent_runner.py` is responsible for updates?
    # I need to check agent_runner.py.
    # BUT, `run_task_agent` also has in-process logic.
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT project_id FROM tasks WHERE id = ?', (task_id,))
    row = cursor.fetchone()
    project_id = row['project_id'] if row else None
    conn.close()
    
    if project_id:
        check_and_update_project_completion(project_id)

    try:
        eel.refreshBoardFromBackend()
    except Exception as e:
        print(f"Error triggering frontend refresh: {e}")

@eel.expose
def run_task_agent(task_id, agent_id=None):
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Get Task
    cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
    task = dict(cursor.fetchone())
    project_id = task.get('project_id') # Save for later

    # Get Project Working Directory
    if task.get('project_id'):
        cursor.execute('SELECT working_dir FROM projects WHERE id = ?', (task['project_id'],))
        project_row = cursor.fetchone()
        if project_row:
            task['working_dir'] = project_row['working_dir']
    
    # 2. Get Agent
    AGENT_CLASSES = {
        "CodingAgent": CodingAgent,
        "ReviewerAgent": ReviewerAgent,
        "GeneratorAgent": GeneratorAgent
    }
    
    agent = None
    if agent_id:
        cursor.execute('SELECT * FROM agents WHERE id = ?', (agent_id,))
        agent_data = dict(cursor.fetchone())
        class_name = agent_data.get('role', 'CodingAgent')
        AgentClass = AGENT_CLASSES.get(class_name, CodingAgent)
        agent = AgentClass(agent_data['name'], SYSTEM_PROMPTS.get(agent_data['system_prompt_key'], ""))
        # Explicitly set show_window from DB
        agent.show_window = bool(agent_data.get('show_window', 0))
    else:
        agent = CodingAgent("Ralph", SYSTEM_PROMPTS.get("coding_agent", "You are a coding agent."))
        agent.show_window = False

    conn.close()
    
    try:
        # Mark In Progress
        conn = get_db()
        conn.execute('UPDATE tasks SET is_inprogress = 1, is_failed = 0 WHERE id = ?', (task_id,))
        conn.commit()
        conn.close()

        if agent.show_window and agent_id:
             # Spawn separate window
             # Use sys.executable to ensure we use the same python env
             # cmd /c allows window to close, but we want to track the process. 
             # On Windows, we can use creationflags to open a new console.
             try:
                 # CREATE_NEW_CONSOLE = 0x00000010
                 CREATE_NEW_CONSOLE = 16
                 
                 # Launch agent_runner directly with python
                 process = subprocess.Popen(
                     [sys.executable, 'agent_runner.py', str(task_id), str(agent_id)],
                     creationflags=CREATE_NEW_CONSOLE,
                     close_fds=True
                 )
                 
                 # Helper thread to wait for process exit and trigger refresh
                 thread = threading.Thread(target=monitor_process, args=(process, task_id, agent.name))
                 thread.daemon = True
                 thread.start()
                 
                 return {"success": True, "message": f"Agent {agent.name} started in new window."}
             except Exception as e:
                 print(f"Failed to launch agent window: {e}")
                 # We'll return error so UI shows it (if UI shows result).
                 return {"success": False, "message": f"Launch Error: {e}"}
        else:
            # Run In-Process
            result = agent.work_on_task(task)
            
            conn = get_db()
            
            if result['success']:
                # Success Logic
                if class_name == "ReviewerAgent":
                    # Review passed!
                    conn.execute('UPDATE tasks SET is_inprogress = 0, is_review = 0, is_complete = 1, is_failed = 0 WHERE id = ?', (task_id,))
                else:
                    # Coding Agent success -> Review
                    conn.execute('UPDATE tasks SET is_inprogress = 0, is_review = 1, is_failed = 0 WHERE id = ?', (task_id,))
            else:
                # Failure Logic
                if class_name == "ReviewerAgent":
                    # Review failed!
                    current_reviews = task.get('review_count', 0)
                    if current_reviews is None: current_reviews = 0
                    
                    new_count = current_reviews + 1
                    max_reviews = int(os.getenv("MAX_REVIEW_ATTEMPTS", 3))
                    
                    if new_count >= max_reviews:
                        print(f"Task {task_id} failed review {new_count} times. Marking as FAILED.")
                        conn.execute('UPDATE tasks SET is_inprogress = 0, is_review = 0, is_complete = 0, is_failed = 1, review_count = ? WHERE id = ?', (new_count, task_id))
                    else:
                        print(f"Task {task_id} failed review {new_count}. Returning to TODO.")
                        # Append feedback to description or just rely on the output logging? 
                        # Ideally we append to a log. For now, let's prepend to description so Coder sees it.
                        feedback = result.get('message', 'Review Failed')
                        new_desc = f"__REVIEW FEEDBACK ({new_count})__:\n{feedback}\n\n" + (task['description'] or "")
                        conn.execute('UPDATE tasks SET is_inprogress = 0, is_review = 0, is_complete = 0, is_failed = 0, review_count = ?, description = ? WHERE id = ?', 
                                    (new_desc, task_id))
                
                else:
                    # Coding Agent failed (fatal error in loop)
                    conn.execute('UPDATE tasks SET is_inprogress = 0, is_failed = 1 WHERE id = ?', (task_id,))
                
            conn.commit()
            conn.close()
            
            # Check for project completion (In-Process)
            if project_id:
                check_and_update_project_completion(project_id)
                
            return result

    except Exception as e:
        print(f"Agent Execution Error: {e}")
        conn = get_db()
        conn.execute('UPDATE tasks SET is_inprogress = 0, is_failed = 1 WHERE id = ?', (task_id,))
        conn.commit()
        conn.close()
        return {"success": False, "message": str(e)}

@eel.expose
def update_agent_config(agent_id, is_active, target_queues):
    # target_queues should be a JSON string list of statuses
    conn = get_db()
    conn.execute('UPDATE agents SET is_active = ?, target_queues = ? WHERE id = ?', 
                 (1 if is_active else 0, target_queues, agent_id))
    conn.commit()
    conn.close()
    return True

@eel.expose
def edit_agent(agent_id, name, role, system_prompt_key, show_window, target_queues):
    conn = get_db()
    conn.execute('''
        UPDATE agents 
        SET name = ?, role = ?, system_prompt_key = ?, show_window = ?, target_queues = ?
        WHERE id = ?
    ''', (name, role, system_prompt_key, 1 if show_window else 0, target_queues, agent_id))
    conn.commit()
    conn.close()
    return True

@eel.expose
def agent_find_work(agent_id):
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Get Agent Config
    cursor.execute('SELECT * FROM agents WHERE id = ?', (agent_id,))
    agent_row = cursor.fetchone()
    if not agent_row:
        conn.close()
        return False
        
    agent = dict(agent_row)
    
    # If not active, do nothing
    if not agent.get('is_active'):
        conn.close()
        return False
        
    # Get Queues
    try:
        queues = json.loads(agent.get('target_queues') or "[]")
    except:
        queues = []
        
    if not queues:
        conn.close()
        return False
        
    # 2. Find eligible task (FIFO)
    # Status match AND no one else working on it (is_inprogress=0)
    # strict status match based on our override logic
    
    # We need to construct a query that checks matches.
    # Since our status logic is complex (computed), we might filter in python or do a complex query.
    # Complex query is better for concurrency but we are single user.
    # Let's do a simple query for candidates then filter.
    
    placeholders = ','.join('?' for _ in queues)
    query = f'''
        SELECT * FROM tasks 
        WHERE is_inprogress = 0 
        AND is_review = 0 
        AND is_complete = 0 
        AND is_failed = 0
    '''
    
    # We need to adapt the query based on what "queue" means.
    # "todo" -> default state (all 0s, and dep met)
    # "review" -> is_review=1
    # "triage" -> is_failed=1
    # "inprogress" -> usually agent doesn't pick up inprogress unless resuming? Let's assume new work only.
    
    # Actually, simpler: Get ALL candidates that MIGHT be relevant, then use python helper to determine "status".
    # Or, map queues to DB columns:
    # 'review' -> is_review = 1
    # 'triage' -> is_failed = 1
    # 'todo' -> is_review=0 AND is_complete=0 AND is_failed=0 AND is_inprogress=0 (and deps met)
    
    candidates = []
    
    # If looking for review
    if 'review' in queues:
        cursor.execute('SELECT * FROM tasks WHERE is_review = 1 AND is_inprogress = 0')
        candidates.extend([dict(r) for r in cursor.fetchall()])
        
    # If looking for triage
    if 'triage' in queues:
        cursor.execute('SELECT * FROM tasks WHERE is_failed = 1 AND is_inprogress = 0')
        candidates.extend([dict(r) for r in cursor.fetchall()])
        
    # If looking for todo
    if 'todo' in queues:
        # Fetch potentials: not complete, not review, not failed, not inprogress
        cursor.execute('''
            SELECT * FROM tasks 
            WHERE is_complete = 0 AND is_review = 0 AND is_failed = 0 AND is_inprogress = 0
        ''')
        potential_todos = [dict(r) for r in cursor.fetchall()]
        
        # Check dependencies
        for t in potential_todos:
            if t['dependency_id']:
                # Check if dependency is complete
                cursor.execute('SELECT is_complete FROM tasks WHERE id = ?', (t['dependency_id'],))
                dep = cursor.fetchone()
                if dep and dep['is_complete']:
                    candidates.append(t)
            else:
                candidates.append(t)

    if not candidates:
        conn.close()
        return False
        
    # Pick first one
    target_task = candidates[0]
    conn.close()
    
    # 3. Trigger Agent
    print(f"Agent {agent['name']} picking up task {target_task['title']}")
    return run_task_agent(target_task['id'], agent_id)

# Initialize Eel
eel.init('web')

if __name__ == "__main__":
    # Start Eel
    try:
        eel.start('index.html', size=(1200, 800))
    except (SystemExit, KeyboardInterrupt):
        print("Application closed")
    except Exception as e:
        print(f"Error starting Eel: {e}")
