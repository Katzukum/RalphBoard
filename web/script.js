function switchTab(tabId) {
    const kanbanView = document.getElementById('kanban-view');
    const agentView = document.getElementById('agent-view');
    const projectsView = document.getElementById('projects-view');

    const tabKanban = document.getElementById('tab-kanban');
    const tabAgent = document.getElementById('tab-agent');
    const tabProjects = document.getElementById('tab-projects');

    // Reset all tabs
    [tabKanban, tabAgent, tabProjects].forEach(t => {
        t.classList.remove('tab-active');
        t.classList.add('text-slate-500');
    });

    // Hide all views
    [kanbanView, agentView, projectsView].forEach(v => v.classList.add('hidden'));

    if (tabId === 'kanban') {
        kanbanView.classList.remove('hidden');
        tabKanban.classList.add('tab-active');
        tabKanban.classList.remove('text-slate-500');
        renderBoard();
    } else if (tabId === 'projects') {
        projectsView.classList.remove('hidden');
        tabProjects.classList.add('tab-active');
        tabProjects.classList.remove('text-slate-500');
        renderProjects();
    } else {
        agentView.classList.remove('hidden');
        tabAgent.classList.add('tab-active');
        tabAgent.classList.remove('text-slate-500');
        renderAgents();
        populatePromptDropdown();
        populateAgentClasses();
    }
}

let tasks = [];

const COLUMNS = [
    { id: 'triage', title: 'Triage' },
    { id: 'backlog', title: 'Backlog' },
    { id: 'todo', title: 'To Do' },
    { id: 'inprogress', title: 'In Progress' },
    { id: 'review', title: 'Review' },
    { id: 'complete', title: 'Complete' }
];

async function init() {
    console.log("Initializing Board...");
    const data = await eel.get_board_data()();
    if (data && data.tasks) {
        tasks = data.tasks;
    }
    renderBoard();
    renderAgents(); // Cache agents too if needed
}

eel.expose(refreshBoardFromBackend);
function refreshBoardFromBackend() {
    console.log("Backend requested board refresh.");
    init();
}

function renderBoard() {
    const boardEl = document.getElementById('board');
    boardEl.innerHTML = '';

    COLUMNS.forEach(col => {
        const colEl = document.createElement('div');
        colEl.className = 'flex-1 min-w-[320px] bg-[#1a1a26] border border-white/5 rounded-xl flex flex-col h-full overflow-hidden';
        colEl.style.boxShadow = '0 4px 20px rgba(0, 0, 0, 0.5)';
        colEl.innerHTML = `
            <div class="p-4 border-b border-cyan-500/10 flex justify-between items-center bg-black/20">
                <h3 class="text-xs font-bold text-white uppercase tracking-widest">${col.title}</h3>
                <span class="text-[10px] font-mono bg-black/40 px-2.5 py-1 rounded border border-white/10 text-slate-500 task-count">0</span>
            </div>
            <div id="${col.id}" class="p-3 flex-grow overflow-y-auto space-y-3 min-h-[50px]">
                <!-- Tasks will go here -->
            </div>
        `;
        boardEl.appendChild(colEl);

        // Initialize Sortable
        new Sortable(document.getElementById(col.id), {
            group: 'kanban',
            animation: 150,
            ghostClass: 'sortable-ghost',
            onEnd: async (evt) => {
                const taskId = evt.item.dataset.id;
                const newStatus = evt.to.id;

                // Call backend based on column
                await eel.update_task_state_from_drag(parseInt(taskId), newStatus)();

                // Re-init to handle calculated statuses (e.g. if moving to Todo and blocked)
                await init();
            }
        });
    });

    // Render tasks
    tasks.forEach(task => {
        const listEl = document.getElementById(task.status || 'backlog');
        if (listEl) {
            const card = createCard(task);
            listEl.appendChild(card);
        }
    });

    updateCounts();
}

function createCard(task) {
    const card = document.createElement('div');
    const isFailed = task.is_failed || task.status === 'triage';
    const bgClass = isFailed ? 'bg-red-900/10' : 'bg-[#12121a]';
    card.className = `${bgClass} p-4 rounded-lg cursor-grab active:cursor-grabbing border relative group transition-all`;
    card.style.borderWidth = '1px';
    card.style.borderColor = isFailed ? 'rgba(255, 71, 87, 0.3)' : 'rgba(255, 255, 255, 0.05)';

    card.dataset.id = task.id;
    card.onclick = () => openEditModal(task);
    card.innerHTML = `
        <div class="flex justify-between items-start mb-2 pointer-events-none">
            <div class="text-[9px] text-cyan-400 font-bold uppercase tracking-widest bg-cyan-500/10 px-2 py-0.5 rounded border border-cyan-500/30">${task.project_name || 'Project'}</div>
            <div class="text-[9px] text-slate-700 font-mono group-hover:text-slate-600 transition-colors">${task.working_dir ? task.working_dir.split(/[\\/]/).pop() : ''}</div>
        </div>
        <div class="text-sm font-medium text-white leading-snug mb-3 pointer-events-none">${task.title}</div>
        ${task.dependency_title ? `
            ${task.dep_is_complete ? `
                <div class="flex items-center gap-1.5 text-[10px] text-green-400/90 border-t border-white/5 pt-2 pointer-events-none">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path><polyline points="22 4 12 14.01 9 11.01"></polyline></svg>
                    <span class="truncate">Dependency Complete: ${task.dependency_title}</span>
                </div>
            ` : `
                <div class="flex items-center gap-1.5 text-[10px] text-yellow-500/80 border-t border-white/5 pt-2 pointer-events-none">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    <span class="truncate">Blocked: ${task.dependency_title}</span>
                </div>
            `}
        ` : ''}
    `;

    // Add hover glow effect
    card.addEventListener('mouseenter', () => {
        if (!isFailed) {
            card.style.borderColor = '#00e5ff';
            card.style.boxShadow = '0 0 15px rgba(0, 229, 255, 0.3)';
        }
    });
    card.addEventListener('mouseleave', () => {
        if (!isFailed) {
            card.style.borderColor = 'rgba(255, 255, 255, 0.05)';
            card.style.boxShadow = 'none';
        }
    });

    return card;
}

function updateCounts() {
    COLUMNS.forEach(col => {
        const container = document.getElementById(col.id);
        const count = container.children.length;
        container.previousElementSibling.querySelector('.task-count').innerText = count;
    });
}

function openModal() {
    document.getElementById('modal').classList.remove('hidden');
    document.getElementById('projectTitle').focus();
}

function closeModal() {
    document.getElementById('modal').classList.add('hidden');
    document.getElementById('projectTitle').value = '';
    document.getElementById('projectDesc').value = '';
    document.getElementById('projectDir').value = '';
}

async function createProject() {
    const titleInput = document.getElementById('projectTitle');
    const descInput = document.getElementById('projectDesc');
    const dirInput = document.getElementById('projectDir');

    const title = titleInput.value.trim();
    const description = descInput.value.trim();
    const workingDir = dirInput.value.trim();

    if (!title || !description) {
        alert("Please provide both a title and a description.");
        return;
    }

    // UI Loading State
    const btn = document.getElementById('create-btn');
    const btnText = document.getElementById('btn-text');
    const btnLoader = document.getElementById('btn-loader');

    btn.disabled = true;
    btnText.innerText = 'Analyzing...';
    btnLoader.classList.remove('hidden');

    try {
        const success = await eel.generate_project_tasks(title, description, workingDir)();

        if (success) {
            await init(); // Refresh everything
            closeModal();
        } else {
            alert("No tasks generated. Check your API key and connection.");
        }
    } catch (e) {
        console.error("Failed to create project:", e);
        alert("Error generating tasks. Check console/backend.");
    } finally {
        btn.disabled = false;
        btnText.innerText = 'Generate Tasks';
        btnLoader.classList.add('hidden');
    }
}

let currentEditingTaskId = null;

function openEditModal(task) {
    currentEditingTaskId = task.id;
    document.getElementById('editTaskTitle').value = task.title;
    document.getElementById('editTaskDesc').value = task.description || '';
    document.getElementById('editTaskSuccess').value = task.success_criteria || '';
    document.getElementById('editProjectName').innerText = task.project_name || 'Project';
    document.getElementById('editInprogress').checked = !!task.is_inprogress;
    document.getElementById('editReview').checked = !!task.is_review;
    document.getElementById('editComplete').checked = !!task.is_complete;
    document.getElementById('editFailed').checked = !!task.is_failed;
    document.getElementById('editReviewCount').value = task.review_count || 0;
    document.getElementById('editCreatedAt').value = task.created_at || '';

    const depSelect = document.getElementById('editTaskDependency');
    depSelect.innerHTML = '<option value="">None</option>';

    // Filter out current task from dependency options
    tasks.forEach(t => {
        if (t.id != task.id) {
            const opt = document.createElement('option');
            opt.value = t.id;
            opt.text = `[${t.project_name}] ${t.title}`;
            if (t.id == task.dependency_id) opt.selected = true;
            depSelect.appendChild(opt);
        }
    });

    document.getElementById('editTaskTitle').onblur = () => saveTaskDetails();
    document.getElementById('editTaskDesc').onblur = () => saveTaskDetails();
    document.getElementById('editTaskSuccess').onblur = () => saveTaskDetails();
    document.getElementById('editTaskDependency').onchange = () => saveTaskDetails();
    document.getElementById('editTaskDependency').onchange = () => saveTaskDetails();
    document.getElementById('editReviewCount').onblur = () => saveTaskDetails();

    // Mutex Logic for Status Checkboxes
    const statusChecks = [
        { id: 'editInprogress', el: document.getElementById('editInprogress') },
        { id: 'editReview', el: document.getElementById('editReview') },
        { id: 'editComplete', el: document.getElementById('editComplete') },
        { id: 'editFailed', el: document.getElementById('editFailed') }
    ];

    statusChecks.forEach(check => {
        check.el.onchange = (e) => {
            if (e.target.checked) {
                // Uncheck others
                statusChecks.forEach(other => {
                    if (other.id !== check.id) other.el.checked = false;
                });
            }
            saveTaskDetails();
        };
    });

    document.getElementById('taskEditModal').classList.remove('hidden');
    document.getElementById('saveStatus').innerText = '';
}

function closeEditModal() {
    document.getElementById('taskEditModal').classList.add('hidden');
    currentEditingTaskId = null;
}

async function saveTaskDetails() {
    if (!currentEditingTaskId) return;

    const title = document.getElementById('editTaskTitle').value;
    const description = document.getElementById('editTaskDesc').value;
    const success_criteria = document.getElementById('editTaskSuccess').value;
    const depId = document.getElementById('editTaskDependency').value;
    const isInProgress = document.getElementById('editInprogress').checked;
    const isReview = document.getElementById('editReview').checked;
    const isComplete = document.getElementById('editComplete').checked;
    const isFailed = document.getElementById('editFailed').checked;

    const statusText = document.getElementById('saveStatus');

    statusText.innerText = 'Saving...';

    try {
        await eel.update_task_details(
            currentEditingTaskId,
            title,
            description,
            success_criteria,
            depId ? parseInt(depId) : null,
            isInProgress,
            isReview,
            isComplete,
            isFailed,
            parseInt(document.getElementById('editReviewCount').value)
        )();
        statusText.innerText = 'Saved!';

        // Refresh board
        await init();

        setTimeout(() => {
            if (statusText.innerText === 'Saved!') statusText.innerText = '';
        }, 1000);
    } catch (e) {
        console.error(e);
        statusText.innerText = 'Error saving';
    }
}

let allAgents = [];

// Agent Manager Logic
async function renderAgents() {
    allAgents = await eel.get_agents()();
    const grid = document.getElementById('agents-grid');
    grid.innerHTML = '';

    if (allAgents.length === 0) {
        grid.innerHTML = `
            <div class="col-span-full py-20 text-center">
                <div class="text-6xl mb-4">🔦</div>
                <p class="text-slate-500">No agents deployed yet. Time to hire some workers!</p>
            </div>
        `;
        return;
    }

    allAgents.forEach(agent => {
        const card = document.createElement('div');
        card.className = 'glow-card p-6 flex flex-col gap-4 relative group rounded-xl';

        // Parse queues safetly
        let queues = [];
        try { queues = JSON.parse(agent.target_queues || '[]'); } catch (e) { }
        const queuesStr = queues.join(', ');

        card.innerHTML = `
            <button onclick="deleteAgent(${agent.id})" class="absolute top-4 right-4 text-slate-700 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all p-1 hover:bg-red-500/10 rounded">
                <svg xmlns="http://www.w3.org/2000/svg" class="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
            </button>
            <div class="flex items-center gap-4">
                <div class="w-10 h-10 rounded-lg bg-gradient-to-br from-cyan-500/20 to-blue-500/20 border border-cyan-500/40 flex items-center justify-center text-lg" style="box-shadow: 0 0 15px rgba(0, 229, 255, 0.2);">
                    🤖
                </div>
                <div>
                    <h3 class="font-bold text-white text-base leading-tight">${agent.name}</h3>
                    <p class="text-[10px] text-cyan-400 uppercase tracking-widest font-bold mt-0.5">${agent.role}</p>
                </div>
            </div>
            
            <!-- Config Section -->
            <div class="bg-black/30 rounded-lg p-3 space-y-3 border border-white/5">
                 <div class="flex items-center justify-between">
                    <span class="text-[10px] text-slate-600 uppercase tracking-wider font-bold">Status</span>
                    <label class="relative inline-flex items-center cursor-pointer">
                        <input type="checkbox" class="sr-only peer" ${agent.is_active ? 'checked' : ''} onchange="toggleAgentActive(${agent.id}, this.checked)">
                        <div class="w-7 h-4 bg-black/50 border border-white/10 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-700 after:rounded-full after:h-3 after:w-3 after:transition-all peer-checked:after:bg-green-400 peer-checked:after:shadow-[0_0_10px_rgba(16,217,124,0.6)]"></div>
                        <span class="ml-2 text-[10px] font-bold uppercase tracking-wider ${agent.is_active ? 'text-green-400' : 'text-slate-700'} transition-all">${agent.is_active ? 'Online' : 'Offline'}</span>
                    </label>
                </div>
                
                <div>
                    <label class="text-[10px] uppercase text-slate-600 tracking-wider block mb-1 font-bold">Queues</label>
                    <input type="text" value="${queuesStr}"
                        class="w-full bg-black/40 border border-white/10 rounded px-2 py-1.5 text-xs text-slate-300 focus:border-cyan-500 focus:shadow-[0_0_10px_rgba(0,229,255,0.3)] outline-none transition-all font-mono"
                        onblur="updateAgentQueues(${agent.id}, this.value)"
                        title="Comma separated statuses">
                </div>
            </div>

            <div class="space-y-1 pt-2 border-t border-white/5">
                <div class="flex justify-between text-xs items-center">
                    <span class="text-[10px] text-slate-600 uppercase tracking-wider font-bold">Directive</span>
                    <span class="text-slate-500 font-mono text-[10px] truncate max-w-[120px] bg-black/40 px-2 py-0.5 rounded border border-white/5">${agent.system_prompt_key}</span>
                </div>
            </div>
        `;
        grid.appendChild(card);
    });
}

async function toggleAgentActive(id, isActive) {
    const agent = allAgents.find(a => a.id === id);
    if (!agent) return;

    // Optimistic update
    agent.is_active = isActive ? 1 : 0;
    renderAgents(); // Re-render to show label change

    await eel.update_agent_config(id, isActive, agent.target_queues)();
}

async function updateAgentQueues(id, queuesStr) {
    const agent = allAgents.find(a => a.id === id);
    if (!agent) return;

    const queues = queuesStr.split(',').map(s => s.trim()).filter(s => s);
    const jsonQueues = JSON.stringify(queues);

    agent.target_queues = jsonQueues;

    await eel.update_agent_config(id, !!agent.is_active, jsonQueues)();
}

// ... existing modal functions ...

async function populatePromptDropdown() {
    try {
        const keys = await eel.get_available_prompts()();
        const select = document.getElementById('agentPromptKey');
        const currentVal = select.value;
        select.innerHTML = '';

        if (!keys || keys.length === 0) {
            const opt = document.createElement('option');
            opt.text = "No prompts found";
            select.appendChild(opt);
        } else {
            keys.forEach(key => {
                const opt = document.createElement('option');
                opt.value = key;
                opt.text = key;
                select.appendChild(opt);
            });
            if (currentVal && keys.includes(currentVal)) select.value = currentVal;
        }
    } catch (e) {
        console.error("Failed to populate prompts:", e);
    }
}

async function populateAgentClasses() {
    try {
        const classes = await eel.get_agent_classes()();
        const select = document.getElementById('agentRole');
        const currentVal = select.value;
        select.innerHTML = '';

        if (!classes || classes.length === 0) {
            const opt = document.createElement('option');
            opt.text = "No classes found";
            select.appendChild(opt);
        } else {
            classes.forEach(cls => {
                const opt = document.createElement('option');
                opt.value = cls;
                opt.text = cls;
                select.appendChild(opt);
            });
            if (currentVal && classes.includes(currentVal)) select.value = currentVal;
        }
    } catch (e) {
        console.error("Failed to populate classes:", e);
    }
}

function renderQueueCheckboxes(containerId, selectedQueues = []) {
    const container = document.getElementById(containerId);
    container.innerHTML = '';

    // Available Boards/Queues
    const queues = ['todo', 'review', 'triage', 'backlog'];

    queues.forEach(q => {
        const isChecked = selectedQueues.includes(q);
        const label = document.createElement('label');
        label.className = 'flex items-center gap-2 cursor-pointer group';
        label.innerHTML = `
            <input type="checkbox" value="${q}" class="hidden peer" ${isChecked ? 'checked' : ''}>
            <div class="w-4 h-4 border border-white/20 rounded peer-checked:bg-blue-500 peer-checked:border-blue-500 transition-all flex items-center justify-center">
                <span class="text-[8px] text-white opacity-0 peer-checked:opacity-100">✔</span>
            </div>
            <span class="text-xs text-slate-400 group-hover:text-white transition-colors capitalize">${q}</span>
        `;
        container.appendChild(label);
    });
}

let editingAgentId = null;

async function openAgentModal(agentId = null) {
    const modal = document.getElementById('agentModal');
    const title = modal.querySelector('h2');
    const btn = document.getElementById('btn-save-agent');

    // Ensure dropdowns are populated
    try {
        await populateAgentClasses();
        await populatePromptDropdown();
    } catch (e) {
        console.error("Error populating dropdowns:", e);
    }

    // Safety check for button (should exist if HTML updated correctly)
    if (!btn) {
        console.error("Btn save agent not found");
        return;
    }

    if (agentId) {
        // Edit Mode
        editingAgentId = agentId;
        const agent = allAgents.find(a => a.id === agentId);
        if (agent) {
            title.innerText = 'Edit Agent';
            btn.innerText = 'Save Changes';
            document.getElementById('agentName').value = agent.name || '';
            document.getElementById('agentRole').value = agent.role || '';
            document.getElementById('agentPromptKey').value = agent.system_prompt_key || '';
            document.getElementById('agentShowWindow').checked = !!agent.show_window;

            let queues = [];
            try { queues = JSON.parse(agent.target_queues || '[]'); } catch (e) { }
            renderQueueCheckboxes('agentQueuesContainer', queues);
        }
    } else {
        // Create Mode
        editingAgentId = null;
        title.innerText = 'Deploy New Agent';
        btn.innerText = 'Deploy Agent';
        document.getElementById('agentName').value = '';
        document.getElementById('agentRole').value = '';
        document.getElementById('agentPromptKey').value = '';
        document.getElementById('agentShowWindow').checked = false;
        renderQueueCheckboxes('agentQueuesContainer', ['todo']); // Default
    }

    modal.classList.remove('hidden');
}

function closeAgentModal() {
    document.getElementById('agentModal').classList.add('hidden');
    editingAgentId = null;
    document.getElementById('agentName').value = '';
    document.getElementById('agentRole').value = '';
    document.getElementById('agentShowWindow').checked = false;
}

async function saveAgent() {
    const name = document.getElementById('agentName').value.trim();
    const role = document.getElementById('agentRole').value.trim();
    const promptKey = document.getElementById('agentPromptKey').value;
    const showWindow = document.getElementById('agentShowWindow').checked;

    // Gather Queues
    const checkboxes = document.querySelectorAll('#agentQueuesContainer input[type="checkbox"]:checked');
    const queues = Array.from(checkboxes).map(cb => cb.value);
    const jsonQueues = JSON.stringify(queues);

    if (!name || !role || !promptKey) {
        alert("Please fill in all fields.");
        return;
    }

    try {
        if (editingAgentId) {
            await eel.edit_agent(editingAgentId, name, role, promptKey, showWindow, jsonQueues)();
        } else {
            await eel.create_agent(name, role, promptKey, showWindow)();
        }
        closeAgentModal();
        renderAgents();
    } catch (e) {
        console.error(e);
        alert("Error saving agent.");
    }
}

async function deleteAgent(id) {
    if (!confirm("Are you sure you want to decommission this agent?")) return;
    try {
        await eel.delete_agent(id)();
        renderAgents();
    } catch (e) {
        console.error(e);
        alert("Error deleting agent.");
    }
}

// Polling Loop
setInterval(async () => {
    // Check for work for all active agents
    if (!allAgents || allAgents.length === 0) return;

    // We iterate sequentially to avoid swamping logic, though requests are async
    for (const agent of allAgents) {
        if (agent.is_active) {
            // We call find_work. usage of await here effectively throttles calls 
            // if the backend blocks on execution. 
            // Ideally we want non-blocking check, but blocking execution is "okay" for a loop of this kind 
            // as long as it doesn't freeze the browser (it shouldn't, unless eel hangs).
            // However, if the agent actually RUNS a task, it returns a result.
            // Only update board if something happened.
            const result = await eel.agent_find_work(agent.id)();
            if (result) {
                console.log(`Agent ${agent.name} finished work:`, result);
                // Refresh Data
                const data = await eel.get_board_data()();
                if (data && data.tasks) tasks = data.tasks;
                renderBoard();
                // Do not re-render agents unless needed to avoid flickering inputs
            }
        }
    }
}, 5000); // Check every 5 seconds

// Start
init();


// Project Manager Logic

async function renderProjects() {
    const projects = await eel.get_projects()();
    const grid = document.getElementById('projects-grid');
    grid.innerHTML = '';

    if (projects.length === 0) {
        grid.innerHTML = `
            <div class="col-span-full py-20 text-center">
                <div class="text-6xl mb-4">📂</div>
                <p class="text-slate-500">No projects found. Create one to get started!</p>
            </div>
        `;
        return;
    }

    projects.forEach(p => {
        const card = document.createElement('div');
        const isCompleted = p.status === 'completed';
        const opacityClass = isCompleted ? 'opacity-50' : '';

        card.className = `glow-card p-6 flex flex-col gap-4 relative group cursor-pointer rounded-xl ${opacityClass}`;
        card.onclick = (e) => {
            openProjectEditModal(p);
        };

        const statusColor = isCompleted ? 'text-green-400 border-green-500/30 bg-green-500/10' : 'text-cyan-400 border-cyan-500/30 bg-cyan-500/10';
        const completionRate = p.total_tasks > 0 ? Math.round((p.completed_tasks / p.total_tasks) * 100) : 0;

        card.innerHTML = `
            <div class="flex items-center justify-between mb-4">
                <h3 class="font-bold text-white text-lg truncate pr-4">${p.name}</h3>
                <span class="text-[9px] uppercase tracking-widest border px-2 py-1 rounded ${statusColor} font-bold">
                    ${p.status || 'Active'}
                </span>
            </div>
            
            <p class="text-sm text-slate-500 line-clamp-2 h-10 mb-6 leading-relaxed">${p.description || 'No description'}</p>
            
            <div class="space-y-2 mt-auto">
                <div class="flex justify-between text-[10px] uppercase tracking-widest text-slate-600 font-bold">
                    <span>Progress</span>
                    <span>${p.completed_tasks} / ${p.total_tasks}</span>
                </div>
                <div class="w-full bg-black/50 h-2 rounded-full overflow-hidden border border-white/5">
                    <div class="bg-gradient-to-r from-cyan-500 to-blue-500 h-full rounded-full transition-all duration-500" style="width: ${completionRate}%; box-shadow: 0 0 10px rgba(0, 229, 255, 0.4);"></div>
                </div>
            </div>
            
            <div class="mt-5 pt-4 border-t border-white/5 text-[10px] text-slate-700 font-mono truncate flex items-center gap-2">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                ${p.working_dir}
            </div>
        `;
        grid.appendChild(card);
    });
}

function openProjectEditModal(project) {
    document.getElementById('editProjectId').value = project.id;
    document.getElementById('editProjectNameInput').value = project.name;
    document.getElementById('editProjectDescInput').value = project.description || '';
    document.getElementById('editProjectDirInput').value = project.working_dir || '';
    document.getElementById('editProjectStatusInput').value = project.status || 'active';

    document.getElementById('projectEditModal').classList.remove('hidden');
}

function closeProjectEditModal() {
    document.getElementById('projectEditModal').classList.add('hidden');
}

async function saveProjectChanges() {
    const id = document.getElementById('editProjectId').value;
    const name = document.getElementById('editProjectNameInput').value;
    const desc = document.getElementById('editProjectDescInput').value;
    const workingDir = document.getElementById('editProjectDirInput').value;
    const status = document.getElementById('editProjectStatusInput').value;

    if (!name) {
        alert("Project name is required");
        return;
    }

    try {
        await eel.update_project(id, name, desc, workingDir, status)();
        closeProjectEditModal();
        renderProjects();
        // Also refresh board if we are on board (or just to be safe)
        init(); // Refresh tasks
    } catch (e) {
        console.error(e);
        alert("Error updating project");
    }
}

async function deleteProject() {
    const id = document.getElementById('editProjectId').value;
    if (!confirm("Are you sure? This will DELETE ALL TASKS associated with this project.")) return;

    try {
        await eel.delete_project(id)();
        closeProjectEditModal();
        renderProjects();
        init(); // Refresh tasks
    } catch (e) {
        console.error(e);
        alert("Error deleting project");
    }
}


// ================== ADD TASK MODAL ==================
async function openAddTaskModal() {
    const modal = document.getElementById('addTaskModal');
    const projectSelect = document.getElementById('addTaskProject');
    const projects = await eel.get_projects()();
    projectSelect.innerHTML = '<option value="">Select Project...</option>';
    projects.forEach(p => {
        const option = document.createElement('option');
        option.value = p.id;
        option.textContent = p.name;
        projectSelect.appendChild(option);
    });
    document.getElementById('addTaskTitle').value = '';
    document.getElementById('addTaskDesc').value = '';
    document.getElementById('addTaskSuccess').value = '';
    document.getElementById('addTaskExpandAI').checked = false;
    modal.classList.remove('hidden');
    document.getElementById('addTaskTitle').focus();
}

function closeAddTaskModal() {
    document.getElementById('addTaskModal').classList.add('hidden');
}

async function createNewTask() {
    const projectId = parseInt(document.getElementById('addTaskProject').value);
    const title = document.getElementById('addTaskTitle').value.trim();
    const description = document.getElementById('addTaskDesc').value.trim();
    const success_criteria = document.getElementById('addTaskSuccess').value.trim();
    const expand_with_ai = document.getElementById('addTaskExpandAI').checked;
    if (!projectId) { alert('Please select a project'); return; }
    if (!title) { alert('Please enter a task title'); return; }
    const btn = document.getElementById('btn-create-task');
    const btnText = document.getElementById('btn-task-text');
    const btnLoader = document.getElementById('btn-task-loader');
    btn.disabled = true;
    btnText.innerText = expand_with_ai ? 'Generating...' : 'Creating...';
    btnLoader.classList.remove('hidden');
    try {
        const result = await eel.create_task(projectId, title, description, success_criteria, expand_with_ai)();
        if (result.success) {
            closeAddTaskModal();
            await init();
            if (result.subtasks_created) {
                alert(`Task created! Generated ${result.subtasks_created} subtasks.`);
            }
        } else {
            alert(`Error: ${result.message || 'Failed to create task'}`);
        }
    } catch (e) {
        console.error(e);
        alert('Error creating task');
    } finally {
        btn.disabled = false;
        btnText.innerText = 'Create';
        btnLoader.classList.add('hidden');
    }
}
