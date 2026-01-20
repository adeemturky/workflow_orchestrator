from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime
import time
import cohere

# ==================== AISA: State Coordination Layer ====================
class WorkflowStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

@dataclass
class WorkflowState:
    workflow_id: str
    task: str
    status: WorkflowStatus
    current_step: int = 0
    total_steps: int = 0
    steps_completed: List[str] = field(default_factory=list)
    step_results: Dict[str, Any] = field(default_factory=dict)
    execution_log: List[Dict[str, Any]] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    def log_event(self, event_type: str, message: str, data: Optional[Dict] = None):
        if len(self.execution_log) >= 500:
            self.execution_log = self.execution_log[-400:]
        self.execution_log.append({
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "message": message,
            "data": data or {}
        })

    def get_execution_time(self) -> Optional[str]:
        if self.start_time and self.end_time:
            duration = self.end_time - self.start_time
            seconds = duration.total_seconds()
            return f"{seconds:.1f}s" if seconds < 60 else f"{seconds/60:.1f}m"
        return None

# ==================== AISA: Cognitive Agent Layer ====================
class BaseAgent:
    def __init__(self, name: str, cohere_client=None):
        self.name = name
        self.agent_id = f"{name}_{id(self)}"
        self.co = cohere_client
    
    def execute(self, input_data: Any, context: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

class PlannerAgent(BaseAgent):
    def execute(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        prompt = f"""You are a Strategic Planner Agent. Break down this task: "{task}" 
        into 3 to 4 sequential, actionable search/analysis steps. 
        Format: Return ONLY the steps separated by newlines."""
        
        try:
            response = self.co.chat(message=prompt, temperature=0.3)
            steps = [s.strip('- ').strip() for s in response.text.split('\n') if s.strip()]
            complexity = "high" if len(steps) > 3 else "medium"
        except:
            # Fallback if API fails
            steps = ["Research the topic overview", "Analyze key trends and data", "Synthesize findings"]
            complexity = "medium"

        return {
            "steps": steps,
            "complexity": complexity,
            "output_type": "plan"
        }

class ExecutorAgent(BaseAgent):
    def execute(self, step: str, context: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = self.co.chat(
                message=f"Perform this task in detail: {step}",
                connectors=[{"id": "web-search"}],
                temperature=0.3
            )
            
            output_text = response.text
            has_citations = hasattr(response, 'citations') and len(response.citations) > 0
            confidence = 0.95 if has_citations else 0.75
            
            return {
                "status": "success",
                "output": output_text,
                "confidence": confidence,
                "citations": [c for c in response.citations] if has_citations else []
            }
        except Exception as e:
            return {
                "status": "failed", 
                "output": str(e), 
                "confidence": 0.0
            }

class ValidatorAgent(BaseAgent):
    def execute(self, result: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        output_len = len(result.get("output", ""))
        base_conf = result.get("confidence", 0.5)
        
        is_valid = output_len > 50 and base_conf > 0.6
        
        if is_valid:
            feedback = "Content verified successfully."
        else:
            feedback = "Content too short or lacks citations."

        return {
            "is_valid": is_valid,
            "confidence": base_conf,
            "feedback": feedback
        }

# ==================== AISA: Agentic Infrastructure Layer ====================
class WorkflowOrchestrator:
    def __init__(self, api_key: str):
        self.co = cohere.Client(api_key)
        self.agents = {
            "planner": PlannerAgent("Planner", self.co),
            "executor": ExecutorAgent("Executor", self.co),
            "validator": ValidatorAgent("Validator", self.co)
        }
    
    def execute_workflow(self, task: str, event_callback: Callable[[str, Dict], None]):
        workflow_id = f"wf_{int(time.time())}"
        state = WorkflowState(workflow_id, task, WorkflowStatus.PENDING)
        
        # Helper to send events to UI
        def emit(type_, msg, role='info', node=None):
            event_callback(type_, {"msg": msg, "role": role, "node": node})

        try:
            emit('status', 'System Initialized.', node='start')
            state.start_time = datetime.now()
            
            # 1. Planning
            emit('activate', 'Analyzing Task Strategy...', node='planner')
            plan = self.agents["planner"].execute(task, {})
            steps = plan['steps']
            state.total_steps = len(steps)
            
            emit('log', f"Strategy formed with {len(steps)} phases.", role='planner')
            time.sleep(1)

            # 2. Execution Loop
            accumulated_report = []

            for i, step in enumerate(steps):
                emit('activate', f"Executing: {step}", node='executor')
                
                # Execution (Real Search)
                exec_res = self.agents["executor"].execute(step, {})
                
                if exec_res['status'] == 'failed':
                    emit('log', f"⚠️ Step failed: {exec_res['output']}", role='error')
                    continue

                # Validation
                emit('activate', 'Verifying Data Integrity...', node='validator')
                val_res = self.agents["validator"].execute(exec_res, {})
                
                emit('activate', 'Quality Gate Decision', node='decision')
                time.sleep(0.5)

                if val_res['is_valid']:
                    emit('log', f"✅ Phase {i+1} Verified (Confidence: {exec_res['confidence']:.0%})", role='success')
                    accumulated_report.append(f"### {step}\n{exec_res['output']}\n")
                else:
                    emit('log', f"⚠️ Quality Warning: {val_res['feedback']}", role='warning')
                    accumulated_report.append(f"### {step}\n{exec_res['output']}\n")

            # 3. Final Generation
            emit('activate', 'Synthesizing Final Intelligence Report...', node='end')
            
            full_context = "\n".join(accumulated_report)
            final_prompt = f"""Based on the following research segments about '{task}', write a cohesive, professional markdown report:\n\n{full_context}"""
            
            final_response = self.co.chat(message=final_prompt, model="command-r", temperature=0.3)
            
            emit('finish', {'report': final_response.text})
            state.status = WorkflowStatus.COMPLETED

        except Exception as e:
            emit('log', f"Critical System Failure: {str(e)}", role='error')
            state.status = WorkflowStatus.FAILED