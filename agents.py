import os
import time
import json
import subprocess
from openai import OpenAI
from dotenv import load_dotenv

from dotenv import load_dotenv
import re

load_dotenv()

def remove_ansi(text):
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

def ensure_opencode_config(working_dir):
    """
    Creates a temporary Opencode config file to auto-approve permissions
    and returns variables to add to the environment.
    """
    config_dir = os.path.join(working_dir, ".opencode")
    os.makedirs(config_dir, exist_ok=True)
    
    config_path = os.path.join(config_dir, "ralph-auto-config.json")
    
    config_data = {
        "$schema": "https://opencode.ai/config.json",
        "permission": {
            "read": "allow",
            "edit": "allow",
            "glob": "allow",
            "grep": "allow",
            "list": "allow",
            "bash": "allow",
            "task": "allow",
            "webfetch": "allow",
            "websearch": "allow",
            "codesearch": "allow",
            "todowrite": "allow",
            "todoread": "allow",
            "question": "allow",
            "lsp": "allow",
            "external_directory": "allow"
        }
    }
    
    with open(config_path, 'w') as f:
        json.dump(config_data, f, indent=2)
        
    return {"OPENCODE_CONFIG": config_path}


class BaseAgent:
    def __init__(self, name, role, system_prompt, show_window=False):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.show_window = show_window
        self.status = "Idle"
        
        # Configure OpenAI
        api_key = os.getenv("OPENAI_API_KEY", "no-key-required")
        base_url = os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:8073/v1")
        self.model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")
        
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url
        )

    def chat(self, user_msg, response_format=None):
        try:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_msg}
            ]
            
            completion_args = {
                "model": self.model_name,
                "messages": messages
            }
            
            if response_format:
                completion_args["response_format"] = response_format
                
            response = self.client.chat.completions.create(**completion_args)
            return response.choices[0].message.content
        except Exception as e:
            print(f"Error in agent {self.name}: {e}")
            return None

class CodingAgent(BaseAgent):
    def __init__(self, name, system_prompt, show_window=False):
        super().__init__(name, "Coder", system_prompt, show_window)

    def find_target_task(self, tasks):
        # Target tasks in 'todo' or 'inprogress'
        for task in tasks:
            if task['status'] in ['todo', 'inprogress']:
                return task
        return None

    def work_on_task(self, task):
        self.status = f"Coding: {task['title']}"
        result = self.ralph_loop(task)
        if result.get("success"):
            return {"success": True, "message": f"Completed task: {task['title']}\nOutput: {result.get('output')}"}
        else:
            return {"success": False, "message": f"FAILED task: {task['title']}\nReason: {result.get('error')}"}

    def ralph_loop(self, task):
        max_iterations = int(os.getenv("MAX_ITERATIONS", 15))
        iteration_count = 1
        failure_log = []
        
        task_prompt = f"""Task Title: {task['title']}
Description: {task.get('description', '')}
Success Criteria: {task.get('success_criteria', '')}"""

        while iteration_count <= max_iterations:
            # Construct the Ralph Prompt (Similar to example)
            failure_context = ""
            if failure_log:
                failure_context = "\n\n## Previous Failed Attempts Log:\n" + "\n".join(failure_log)
            
            ralph_prompt = f"""
# Ralph Wiggum Loop - Iteration {iteration_count} / {max_iterations}

You are in an iterative development loop. Work on the task below until you can genuinely complete it.

## Your Task
{task_prompt}

{failure_context}

## Instructions
1. Read the current state of files to understand what's been done.
2. Make progress on the task.
3. Run tests/verification if applicable.
4. When the task is GENUINELY COMPLETE, output:
   <promise>COMPLETE</promise>

## Critical Rules
- ONLY output <promise>COMPLETE</promise> when the task is truly done.
- Do NOT lie or output false promises to exit the loop.
- If you failed in previous iterations, analyze the failure log and TRY A DIFFERENT APPROACH.
- The loop will continue until you succeed or we run out of iterations.

Now, work on the task. Good luck!
"""
            self.status = f"Coding: {task['title']} (Iter {iteration_count}/{max_iterations})"
            print(f"[{self.name}] Starting Iteration {iteration_count}...")
            
            # Execute Opencode CLI
            full_output = ""
            try:
                # Use a primer message as arg and pass the full context via stdin
                # This avoids Windows argument length/parsing issues with multiline strings
                primer_msg = "Please follow the iterative development instructions provided in the input below."
                
                
                working_dir = task.get('working_dir')
                print(f"[{self.name}] Working Directory: {working_dir}")
                
                # Setup auto-approve config
                env_updates = ensure_opencode_config(working_dir)
                proc_env = os.environ.copy()
                proc_env.update(env_updates)

                process = subprocess.Popen(
                    ["opencode.cmd", "run", primer_msg],
                    cwd=working_dir,
                    env=proc_env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    shell=True
                )


                # Write prompt to stdin and close
                process.stdin.write(ralph_prompt)
                process.stdin.close()

                for line in process.stdout:
                    print(line, end='')
                    full_output += line
                
                process.wait()
                
            except Exception as e:
                print(f"[{self.name}] | Execution Error: {e}")
                failure_log.append(f"Iteration {iteration_count} Execution Error: {e}")
                iteration_count += 1
                time.sleep(1)
                continue

            # Check for completion promise
            if "<promise>COMPLETE</promise>" in full_output:
                print(f"[{self.name}] Completion promise detected in Iteration {iteration_count}!")
                return {"success": True, "output": full_output}
            
            log_entry = f"Iteration {iteration_count} Result: Did not complete. Output snippet: {full_output[-200:]}..."
            failure_log.append(log_entry)
            
            iteration_count += 1
            time.sleep(1) # Brief pause

        # If we exit the loop, we failed
        return {"success": False, "error": "Max iterations reached without completion promise."}

class ReviewerAgent(BaseAgent):
    def __init__(self, name, system_prompt, show_window=False):
        super().__init__(name, "Reviewer", system_prompt, show_window)

    def find_target_task(self, tasks):
        # Target tasks in 'review' status
        for task in tasks:
            if task['status'] == 'review':
                return task
        return None

    def work_on_task(self, task):
        self.status = f"Reviewing: {task['title']}"
        print(f"[{self.name}] Starting review for task: {task['title']}")
        
        max_iterations = int(os.getenv("MAX_REVIEW_ITERATIONS", 5))
        iteration_count = 1
        full_log = []
        
        task_info = f"""Task Title: {task['title']}
Description: {task.get('description', '')}
Success Criteria: {task.get('success_criteria', '')}"""

        working_dir = task.get('working_dir')
        

        while iteration_count <= max_iterations:
            previous_context = ""
            if full_log:
                previous_context = "\n\n## Review Progress Log:\n" + "\n".join(full_log[-3:])

            review_prompt = f"""
# Task Review - Iteration {iteration_count} / {max_iterations}

You are a strict QA Reviewer. Your job is to verify if the following task has been completed correctly.

## The Task
{task_info}

{previous_context}

## Instructions
1. Explore the codebase (list files, read files) to verify the implementation.
2. Check if the Success Criteria are met. in the working directory: {working_dir}
3. If you need more information, use tools to get it.
4. If the task is GENUINELY COMPLETE and meets all criteria:
   - Output: <promise>COMPLETE</promise>
5. If there are issues, bugs, or missing requirements:
   - List the specific issues clearly.
   - Output: <promise>REJECTED</promise> (This acts as the fail signal)

## Critical Rules
- You MUST explicitly output <promise>COMPLETE</promise> or <promise>REJECTED</promise> when you have made a decision.
- Do NOT just stop without a decision.
- If you run out of iterations, the review defaults to REJECTED.

Begin your review step.
"""
            print(f"[{self.name}] Starting Review Iteration {iteration_count}...")
            
            try:
                primer_msg = "Please continue the review process."
                
                
                
                
                print(f"[{self.name}] Working Directory: {working_dir}")
                
                # Setup auto-approve config
                env_updates = ensure_opencode_config(working_dir)
                proc_env = os.environ.copy()
                proc_env.update(env_updates)

                process = subprocess.Popen(
                    ["opencode.cmd", "run", primer_msg],
                    cwd=working_dir,
                    env=proc_env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    shell=True
                )


                process.stdin.write(review_prompt)
                process.stdin.close()

                current_output = ""
                for line in process.stdout:
                    print(line, end='')
                    current_output += line
                
                process.wait()
                
                if "<promise>COMPLETE</promise>" in current_output:
                    print(f"[{self.name}] Task Approved!")
                    return {"success": True, "message": "Task Approved by Reviewer"}
                
                if "<promise>REJECTED</promise>" in current_output:
                    print(f"[{self.name}] Task Rejected.")
                    clean_msg = remove_ansi(current_output)
                    return {"success": False, "message": clean_msg}
                
                log_entry = f"Iteration {iteration_count} Output Snippet: {current_output[-300:]}..."
                full_log.append(log_entry)
                
                iteration_count += 1
                time.sleep(1)

            except Exception as e:
                print(f"[{self.name}] Review execution error: {e}")
                return {"success": False, "message": f"Review execution error: {e}"}

        return {"success": False, "message": "Reviewer timed out (max iterations reached) without a clear decision. Defaulting to Rejection."}

class GeneratorAgent(BaseAgent):
    def __init__(self, name, system_prompt, show_window=False):
        super().__init__(name, "Generator", system_prompt, show_window)

    def generate_tasks(self, project_title, description, working_dir):
        self.status = "Generating Tasks"
        user_prompt = f"Project Title: {project_title}\nProject Context/Description: {description}\nWorking Directory: {working_dir}"
        response_format = {"type": "json_object"}
        system_msg = self.system_prompt + "\nWrap your response in a json object with a 'tasks' key."
        
        # Override system prompt temporarily for JSON structure
        original_prompt = self.system_prompt
        self.system_prompt = system_msg
        
        result = self.chat(user_prompt, response_format)
        
        self.system_prompt = original_prompt
        return json.loads(result) if result else None
