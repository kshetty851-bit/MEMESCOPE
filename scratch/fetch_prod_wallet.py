import subprocess
import json
from datetime import datetime, timezone

cmd = ['ssh', 'ubuntu@51.79.166.133', 'docker exec memescope-backend-1 bash -c "curl -s -c /tmp/cookies.txt -X POST -H \'Content-Type: application/json\' -d \'{\\\"code\\\": \\\"619554\\\"}\' http://localhost:8000/api/v1/alpha/verify > /dev/null && curl -s -b /tmp/cookies.txt http://localhost:8000/api/v1/paper/wallet"']
result = subprocess.run(cmd, capture_output=True, text=True)

try:
    data = json.loads(result.stdout)
    now = datetime.now(timezone.utc)
    open_pos = [p for p in data['positions'] if p['status'] == 'open']
    print(f"Total open: {len(open_pos)}")

    stale = 0
    no_price = 0
    age_list = []
    
    for p in open_pos:
        if p.get('current_price_at') is None:
            no_price += 1
            continue
        pt = datetime.fromisoformat(p['current_price_at'].replace('Z', '+00:00'))
        age = (now - pt).total_seconds()
        age_list.append(age)
        if age > 300:
            stale += 1

    print(f"Stale (>5m): {stale}")
    print(f"No price: {no_price}")
    
    if age_list:
        age_list.sort()
        print(f"Median age: {age_list[len(age_list)//2]}s")
        print(f"p95 age: {age_list[int(len(age_list)*0.95)]}s")
        
except Exception as e:
    print(f"Error parsing json: {e}")
    print("Stdout:", result.stdout[:500])
    print("Stderr:", result.stderr[:500])
