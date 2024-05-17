import subprocess
import xml.etree.ElementTree as ET
import cv2

# Function to extract bounds from the node attributes
def extract_bounds(node):
    bounds_str = node.get("bounds")
    if bounds_str:
        bounds_str = bounds_str.replace("[", "").replace("]", ",")
        bounds = [int(coord) for coord in bounds_str.strip(",").split(",")]
        return bounds
    return None

# Set to keep track of processed bounds
processed_bounds = set()

while True:
    result = subprocess.run('adb devices', shell=True, capture_output=True, text=True)
    
    devices_info = result.stdout.strip().split('\n')[1:]
    
    if len(devices_info) > 0:
        device_id = devices_info[0].split('\t')[0]
        
        # Command to capture UI hierarchy
        ui_capture_command = f'adb -s {device_id} shell uiautomator dump /sdcard/snapchat_ui.xml'
        subprocess.run(ui_capture_command, shell=True)
        
        # Command to pull the UI file from the device
        pull_command = f'adb -s {device_id} pull /sdcard/snapchat_ui.xml snapchat_ui.xml'
        subprocess.run(pull_command, shell=True)
        
        tree = ET.parse('snapchat_ui.xml')
        root = tree.getroot()
        
        # Find all nodes with bounds and print their positions
        print("Nodes with Bounds:")
        for idx, node in enumerate(root.iter()):
            bounds = extract_bounds(node)
            if bounds:
                print(f"{idx+1}. Bounds: {bounds}")
        
        # Capture screenshot of the current app window
        screenshot_command = f'adb -s {device_id} shell screencap -p /sdcard/snapchat_screenshot.png'
        subprocess.run(screenshot_command, shell=True)
        
        # Pull the screenshot from the device
        pull_screenshot_command = f'adb -s {device_id} pull /sdcard/snapchat_screenshot.png snapchat_screenshot.png'
        subprocess.run(pull_screenshot_command, shell=True)
        
        # Read the screenshot
        screenshot = cv2.imread('snapchat_screenshot.png')
        
        # Write numbers on the screenshot corresponding to node positions
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1
        font_color = (0, 0, 0)  # Black color
        thickness = 2
        
        # Define the offset for the outline
        offset = 2
        
        # Draw the white outline and write numbers
        for idx, node in enumerate(root.iter()):
            bounds = extract_bounds(node)
            if bounds:
                if tuple(bounds) not in processed_bounds:
                    processed_bounds.add(tuple(bounds))
                    x = bounds[0] + 10
                    y = bounds[1] + 30
                    cv2.putText(screenshot, str(idx+1), (x - offset, y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
                    cv2.putText(screenshot, str(idx+1), (x + offset, y), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
                    cv2.putText(screenshot, str(idx+1), (x, y - offset), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
                    cv2.putText(screenshot, str(idx+1), (x, y + offset), font, font_scale, (255, 255, 255), thickness, cv2.LINE_AA)
                    cv2.putText(screenshot, str(idx+1), (x, y), font, font_scale, font_color, thickness, cv2.LINE_AA)
        
        # Save the modified screenshot
        cv2.imwrite('annotated_screenshot.png', screenshot)
        
        break
