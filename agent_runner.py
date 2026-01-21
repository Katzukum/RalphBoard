import sys
import sqlite3
import json
import traceback
import os
from agents import CodingAgent, ReviewerAgent, GeneratorAgent
from prompts import SYSTEM_PROMPTS
from dotenv import load_dotenv

load_dotenv()

# Replicate DB connection from app.py
def get_db():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(base_dir, 'ralphboard.db')
    print(f"DEBUG: Connecting to DB at {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def main():
    if len(sys.argv) < 3:
        print("Usage: python agent_runner.py <task_id> <agent_id>")
        input("Press Enter to exit...")
        return

    task_id = sys.argv[1]
    agent_id = sys.argv[2]

    print(f"--- Agent Runner Starting for Task {task_id} (Agent {agent_id}) ---")
    
    try:
        conn = get_db()
        cursor = conn.cursor()

        # 1. Get Task
        cursor.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
        task_row = cursor.fetchone()
        if not task_row:
            print(f"Error: Task {task_id} not found.")
            conn.close()
            return
        task = dict(task_row)

        # Get Project Working Directory
        if task.get('project_id'):
            cursor.execute('SELECT working_dir FROM projects WHERE id = ?', (task['project_id'],))
            project_row = cursor.fetchone()
            if project_row:
                task['working_dir'] = project_row['working_dir']

        # 2. Get Agent
        cursor.execute('SELECT * FROM agents WHERE id = ?', (agent_id,))
        agent_row = cursor.fetchone()
        if not agent_row:
            print(f"Error: Agent {agent_id} not found.")
            conn.close()
            return
        agent_data = dict(agent_row)
        conn.close()

        # 3. Instantiate Agent
        AGENT_CLASSES = {
            "CodingAgent": CodingAgent,
            "ReviewerAgent": ReviewerAgent,
            "GeneratorAgent": GeneratorAgent
        }
        
        class_name = agent_data.get('role', 'CodingAgent')
        AgentClass = AGENT_CLASSES.get(class_name, CodingAgent)
        system_prompt = SYSTEM_PROMPTS.get(agent_data.get('system_prompt_key'), "")
        if not system_prompt:
             # Fallback if key not found or empty
             system_prompt = "You are an AI assistant."

        agent = AgentClass(agent_data['name'], system_prompt, show_window=True)
        print(f"Agent: {agent.name} ({class_name})")
        print(f"Task: {task['title']}")
        print("-" * 40)

        # 4. Run Task
        # Note: Task status is already 'In Progress' set by app.py before launching this
        result = agent.work_on_task(task)
        
        # 5. Update DB based on result
        conn = get_db()
        cursor = conn.cursor()
        
        if result['success']:
            print("\nSUCCESS!")
            if class_name == "ReviewerAgent":
                # Review passed!
                cursor.execute('UPDATE tasks SET is_inprogress = 0, is_review = 0, is_complete = 1, is_failed = 0 WHERE id = ?', (int(task_id),))
                print(f"DEBUG: Task {task_id} approved and marked complete.")
            else:
                # Coding Agent success -> Review
                cursor.execute('UPDATE tasks SET is_inprogress = 0, is_review = 1, is_failed = 0 WHERE id = ?', (int(task_id),))
                print(f"DEBUG: Task {task_id} implementation success. Moving to review.")
        else:
            print("\nFAILURE.")
            feedback = result.get('message', 'Unknown error')
            print(f"Reason: {feedback}")
            
            if class_name == "ReviewerAgent":
                # Review failed!
                current_reviews = task.get('review_count', 0)
                if current_reviews is None: current_reviews = 0
                
                new_count = current_reviews + 1
                max_reviews = int(os.getenv("MAX_REVIEW_ATTEMPTS", 3))
                
                if new_count >= max_reviews:
                    print(f"Task {task_id} failed review {new_count} times. Marking as FAILED.")
                    cursor.execute('UPDATE tasks SET is_inprogress = 0, is_review = 0, is_complete = 0, is_failed = 1, review_count = ? WHERE id = ?', (new_count, int(task_id)))
                else:
                    print(f"Task {task_id} failed review {new_count}. Returning to TODO.")
                    # Prepend feedback to description
                    new_desc = f"__REVIEW FEEDBACK ({new_count})__:\n{feedback}\n\n" + (task['description'] or "")
                    cursor.execute('UPDATE tasks SET is_inprogress = 0, is_review = 0, is_complete = 0, is_failed = 0, review_count = ?, description = ? WHERE id = ?', 
                                  (new_count, new_desc, int(task_id)))
            else:
                # Coding Agent failed
                cursor.execute('UPDATE tasks SET is_inprogress = 0, is_failed = 1 WHERE id = ?', (int(task_id),))
                
        conn.commit()
        conn.close()
        print("-" * 40)

    except Exception as e:
        print(f"\nCRITICAL ERROR: {e}")
        traceback.print_exc()
        try:
            # Attempt to set task to failed so it doesn't hang in progress
            conn = get_db()
            conn.execute('UPDATE tasks SET is_inprogress = 0, is_failed = 1 WHERE id = ?', (task_id,))
            conn.commit()
            conn.close()
        except:
            pass
    
    print("\nSession Finished.")
    
    # Check for DEBUG flag to keep window open
    if os.getenv("DEBUG", "").lower() == "true":
        input("Press Enter to close window (DEBUG mode)...")

if __name__ == "__main__":
    main()
