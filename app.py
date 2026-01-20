from flask import Flask, render_template, request, Response, stream_with_context
import json
import time
from workflow_orchestrator import WorkflowOrchestrator

app = Flask(__name__)

# ==================== CONFIGURATION ====================
COHERE_API_KEY = "KEY"

# ==================== FLASK ROUTES ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/stream_workflow')
def stream_workflow():
    task = request.args.get('task', 'Search about KSA Vision 2030')
    
    def generate():
        orchestrator = WorkflowOrchestrator(COHERE_API_KEY)
        
        def on_event(event_type, payload):
            data = {
                'type': event_type,
            }
            
            if isinstance(payload, dict):
                data.update(payload)
            
        # 1. Start
        yield f"data: {json.dumps({'type': 'status', 'node': 'start', 'msg': 'Connecting to Neural Network...'})}\n\n"
        
        yield f"data: {json.dumps({'type': 'activate', 'node': 'planner', 'msg': 'Planner: Analyzing complexity...'})}\n\n"
        plan = orchestrator.agents["planner"].execute(task, {})
        steps = plan['steps']
        yield f"data: {json.dumps({'type': 'log', 'msg': f'Strategized {len(steps)} execution steps based on real analysis.', 'role': 'planner'})}\n\n"

        accumulated_data = ""

        # 2. Execution Loop
        for i, step in enumerate(steps):
            yield f"data: {json.dumps({'type': 'activate', 'node': 'executor', 'msg': f'Researching: {step}'})}\n\n"
            
            exec_res = orchestrator.agents["executor"].execute(step, {})
            accumulated_data += f"\nSection {i+1}: {step}\n{exec_res['output']}\n"
            
            yield f"data: {json.dumps({'type': 'activate', 'node': 'validator', 'msg': 'Verifying sources...'})}\n\n"
            val_res = orchestrator.agents["validator"].execute(exec_res, {})
            
            yield f"data: {json.dumps({'type': 'activate', 'node': 'decision', 'msg': 'Quality Gate'})}\n\n"
            
            if val_res['is_valid']:
                citations_count = len(exec_res.get('citations', []))
                yield f"data: {json.dumps({'type': 'log', 'msg': f'✅ Validated with {citations_count} citations.', 'role': 'success'})}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'log', 'msg': f'⚠️ Low confidence data.', 'role': 'warning'})}\n\n"
            
            time.sleep(0.5)

        # 3. Final Report
        yield f"data: {json.dumps({'type': 'activate', 'node': 'end', 'msg': 'Generating Final Report...'})}\n\n"
        
        final_prompt = f"""
        You are an AI analyst. The user asked: "{task}".
        Based on the following research data, write a comprehensive executive summary in Markdown:
        
        {accumulated_data}
        """
        final_report = orchestrator.co.chat(message=final_prompt, model="command-a-03-2025", temperature=0.3).text
        
        yield f"data: {json.dumps({'type': 'finish', 'report': final_report})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')

if __name__ == '__main__':
    app.run(debug=True, port=5000)