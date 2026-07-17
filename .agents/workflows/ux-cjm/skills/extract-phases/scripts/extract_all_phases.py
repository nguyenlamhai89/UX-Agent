import os
import argparse
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

PHASE_CONFIG = {
    "awareness": {
        "themes": ["1. awareness", "awareness"],
        "output": "extracted-awareness.md"
    },
    "consideration": {
        "themes": ["2. consideration", "consideration"],
        "output": "extracted-consideration.md"
    },
    "decision_making": {
        "themes": ["3. decision making", "decision making"],
        "output": "extracted-decision-making.md"
    },
    "usage": {
        "themes": ["4. usage", "usage"],
        "output": "extracted-usage.md"
    },
    "advocacy": {
        "themes": ["5. advocacy", "advocacy"],
        "output": "extracted-advocacy.md"
    }
}

def extract_all_phases(folder_path):
    input_path = os.path.join(folder_path, "mapped-transcript.md")
    journey_map_dir = os.path.join(folder_path, "Journey Map")
    
    if not os.path.exists(input_path):
        logging.error(f"Input file {input_path} not found.")
        return False
        
    os.makedirs(journey_map_dir, exist_ok=True)
    
    # Pre-open all 5 file handlers
    file_handlers = {}
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        header_line = None
        separator_line = None
        theme_col_idx = -1
        
        # Determine header first
        header_index = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith('|') and stripped.endswith('|'):
                if i + 1 < len(lines):
                    next_line = lines[i+1].strip()
                    if next_line.startswith('|') and next_line.endswith('|') and '---' in next_line:
                        header_line = line
                        separator_line = lines[i+1]
                        cells = [cell.strip() for cell in stripped.split('|')[1:-1]]
                        for col_idx, cell in enumerate(cells):
                            if cell.lower() == 'theme':
                                theme_col_idx = col_idx
                                break
                        if theme_col_idx == -1:
                            logging.error("Could not find 'Theme' column in the table.")
                            return False
                        header_index = i
                        break
                        
        if header_index == -1:
            logging.error("Could not parse markdown table header.")
            return False
            
        # Open files and write headers
        for phase, config in PHASE_CONFIG.items():
            output_path = os.path.join(journey_map_dir, config["output"])
            handler = open(output_path, 'w', encoding='utf-8')
            handler.write(header_line)
            handler.write(separator_line)
            file_handlers[phase] = handler
            
        # Process rows
        row_counts = {phase: 0 for phase in PHASE_CONFIG.keys()}
        for i in range(header_index + 2, len(lines)):
            line = lines[i]
            stripped = line.strip()
            if not stripped.startswith('|') or not stripped.endswith('|'):
                continue
                
            cells = [cell.strip() for cell in stripped.split('|')[1:-1]]
            
            if len(cells) <= theme_col_idx:
                logging.warning(f"Malformed table row at line {i+1}: Missing Theme column.")
                continue
                
            theme_val = cells[theme_col_idx].lower()
            matched = False
            for phase, config in PHASE_CONFIG.items():
                if theme_val in config["themes"]:
                    file_handlers[phase].write(line)
                    row_counts[phase] += 1
                    matched = True
                    break
                    
            if not matched:
                logging.warning(f"Row at line {i+1} has an unrecognized Theme: '{theme_val}'.")

        for phase, config in PHASE_CONFIG.items():
            logging.info(f"Successfully extracted {row_counts[phase]} rows to {config['output']}")
            
        return True
        
    except Exception as e:
        logging.error(f"Error during extraction: {e}")
        return False
    finally:
        for handler in file_handlers.values():
            handler.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract all phases from mapped-transcript.md")
    parser.add_argument("--folder-path", required=True, help="Path to the folder containing mapped-transcript.md")
    args = parser.parse_args()
    
    success = extract_all_phases(args.folder_path)
    if not success:
        exit(1)
