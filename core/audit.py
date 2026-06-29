import json
import os
import aiofiles

AUDIT_FILE = 'core/data_lake/audit_state.json'

async def increment_audit(metric: str):
    data = {'restarts': 0, 'disconnects': 0}
    if os.path.exists(AUDIT_FILE):
        try:
            async with aiofiles.open(AUDIT_FILE, 'r') as f:
                content = await f.read()
                if content.strip():
                    data = json.loads(content)
        except Exception:
            pass
            
    if metric == 'restart':
        data['restarts'] = data.get('restarts', 0) + 1
    elif metric == 'disconnect':
        data['disconnects'] = data.get('disconnects', 0) + 1
        
    try:
        async with aiofiles.open(AUDIT_FILE, 'w') as f:
            await f.write(json.dumps(data))
    except Exception:
        pass
