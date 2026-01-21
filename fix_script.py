# Fix corrupted JavaScript file by removing null bytes
import re

# Read the corrupted file
with open(r'C:\Users\desk\Desktop\Javascript Projects\RalphBoard\web\script.js', 'rb') as f:
    content = f.read()

# Find the start of corruption (line 740, after deleteProject function)
# Find the first occurrence of null bytes
null_start = content.find(b'\x00')
if null_start > 0:
    # Find where the corruption ends (line 818 where clean code starts)
    # Look for the clean "// ================== ADD TASK MODAL" without null bytes
    clean_marker = b'// ================== ADD TASK MODAL'
    
    # Find all occurrences
    marker_positions = []
    start = 0
    while True:
        pos = content.find(clean_marker, start)
        if pos == -1:
            break
        # Check if this occurrence has null bytes before it (corrupted) or not (clean)
        if pos > 0 and content[pos-1] != 0:
            marker_positions.append(pos)
        start = pos + 1
    
    if len(marker_positions) >= 1:
        # Use the last occurrence (the clean one)
        clean_start = marker_positions[-1]
        
        # Keep everything before corruption and everything from clean marker onwards
        clean_content = content[:null_start-1] + b'\n\n' + content[clean_start:]
        
        # Write the fixed file
        with open(r'C:\Users\desk\Desktop\Javascript Projects\RalphBoard\web\script.js', 'wb') as f:
            f.write(clean_content)
        
        print(f"Fixed! Removed {clean_start - null_start} corrupted bytes")
    else:
        print("Could not find clean marker")
else:
    print("No corruption found")
