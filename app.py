import os
import tempfile
from flask import Flask, render_template, request, flash, redirect, url_for, jsonify
from werkzeug.utils import secure_filename
from flask_socketio import SocketIO
import subprocess
import time
import json
import re

app = Flask(__name__)
app.secret_key = os.urandom(24)
socketio = SocketIO(app)

ALLOWED_EXTENSIONS = {'py', 'php', 'html', 'js', 'css'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_linter_command(file_path, file_type):
    """Return the appropriate linter command based on file type"""
    commands = {
        'py': ['pylint', '--output-format=json', file_path],
        'php': ['phpcs', '--standard=PSR2', '--report=json', file_path],
        'html': ['htmlhint', '--format=json', file_path],
        'js': ['eslint', '-f', 'json', file_path],
        'css': ['stylelint', '--formatter=json', file_path]
    }
    return commands.get(file_type, None)

def analyze_code_quality(result, file_type):
    """Analyze code quality and return a score and detailed feedback"""
    try:
        score = 10  # Start with perfect score and deduct based on issues
        issues = []
        improvement_areas = {
            'performance': [],
            'maintainability': [],
            'style': [],
            'security': []
        }
        
        if file_type == 'py':
            # Parse pylint JSON output
            try:
                data = json.loads(result)
                total_deduction = 0
                
                # Weight different issue types
                weights = {
                    'convention': 0.1,    # Style conventions
                    'refactor': 0.2,      # Refactoring suggestions
                    'warning': 0.3,       # Python-specific warnings
                    'error': 0.5,         # Serious errors
                    'fatal': 1.0          # Critical errors
                }
                
                for issue in data:
                    msg_type = issue.get('type', '').lower()
                    message = issue.get('message', '')
                    line = issue.get('line', 0)
                    
                    # Calculate weighted deduction
                    deduction = weights.get(msg_type, 0.2)
                    
                    # Adjust deduction based on issue severity
                    if 'unused' in message.lower():
                        deduction *= 0.5  # Less severe for unused variables
                    elif 'line too long' in message.lower():
                        deduction = 0.1   # Minor issue for line length
                    elif 'missing docstring' in message.lower():
                        deduction = 0.15  # Documentation issues
                    
                    total_deduction += deduction
                    
                    # Categorize issues
                    category = 'style'
                    if msg_type in ['error', 'fatal'] or 'error' in message.lower():
                        category = 'maintainability'
                    elif 'performance' in message.lower() or 'complexity' in message.lower():
                        category = 'performance'
                    elif 'security' in message.lower() or 'unsafe' in message.lower():
                        category = 'security'
                    
                    issue_info = f"Line {line}: {message}"
                    improvement_areas[category].append(issue_info)
                    issues.append(issue_info)
                
                # Calculate final score with diminishing returns
                score = max(0, min(10, 10 - (total_deduction * 0.8)))
                
            except json.JSONDecodeError:
                # Fallback for non-JSON output
                error_count = len(re.findall(r'error|fatal', result, re.I))
                warning_count = len(re.findall(r'warning', result, re.I))
                convention_count = len(re.findall(r'convention|refactor', result, re.I))
                
                total_deduction = (error_count * 0.5) + (warning_count * 0.3) + (convention_count * 0.1)
                score = max(0, min(10, 10 - total_deduction))
                
                # Parse issues from text output
                for line in result.split('\n'):
                    if any(level in line.lower() for level in ['error', 'warning', 'convention', 'refactor']):
                        issues.append(line.strip())
                        improvement_areas['style'].append(line.strip())
            
        elif file_type == 'php':
            try:
                # Parse PHP_CodeSniffer JSON output
                data = json.loads(result)
                total_deduction = 0
                
                for file_path, file_data in data.get('files', {}).items():
                    messages = file_data.get('messages', [])
                    
                    # Group similar issues to prevent over-penalization
                    issue_types = {}
                    
                    for msg in messages:
                        severity = msg.get('type', 'ERROR')
                        message = msg.get('message', '')
                        line = msg.get('line', 0)
                        source = msg.get('source', '')
                        
                        # Group similar issues
                        if source not in issue_types:
                            issue_types[source] = 1
                        else:
                            issue_types[source] += 1
                        
                        # Calculate deduction with diminishing returns
                        if severity == 'ERROR':
                            base_deduction = 0.4
                        else:  # WARNING
                            base_deduction = 0.2
                        
                        # Apply diminishing returns for repeated issues
                        deduction = base_deduction / (issue_types[source] ** 0.5)
                        
                        # Adjust deduction based on issue type
                        if 'line exceeds' in message.lower():
                            deduction = 0.1
                        elif 'missing doc comment' in message.lower():
                            deduction = 0.15
                        elif 'unused' in message.lower():
                            deduction = 0.2
                        
                        total_deduction += deduction
                        
                        # Categorize issues
                        category = 'style'
                        if 'error' in severity.lower() or 'critical' in message.lower():
                            category = 'maintainability'
                        elif any(term in message.lower() for term in ['performance', 'slow', 'memory']):
                            category = 'performance'
                        elif any(term in message.lower() for term in ['security', 'sanitize', 'escape']):
                            category = 'security'
                        
                        issue_info = f"Line {line}: {message}"
                        improvement_areas[category].append(issue_info)
                        issues.append(issue_info)
                
                # Calculate final score with soft cap
                score = max(2, min(10, 10 - (total_deduction * 0.7)))
                
            except json.JSONDecodeError:
                # Handle non-JSON output
                error_count = len(re.findall(r'ERROR', result, re.I))
                warning_count = len(re.findall(r'WARNING', result, re.I))
                notice_count = len(re.findall(r'NOTICE', result, re.I))
                
                total_deduction = (error_count * 0.4) + (warning_count * 0.2) + (notice_count * 0.1)
                score = max(2, min(10, 10 - total_deduction))
                
                for line in result.split('\n'):
                    if any(level in line.upper() for level in ['ERROR', 'WARNING', 'NOTICE']):
                        issues.append(line.strip())
                        improvement_areas['style'].append(line.strip())
        
        # Prepare improvement suggestions
        suggestions = []
        categories = {
            'performance': '🚀 Performance',
            'maintainability': '🔧 Maintainability',
            'style': '✨ Code Style',
            'security': '🔒 Security'
        }
        
        for category, issues_list in improvement_areas.items():
            if issues_list:
                suggestions.append({
                    'category': categories[category],
                    'issues': issues_list[:3],  # Show top 3 issues per category
                    'count': len(issues_list)
                })
        
        # Sort suggestions by number of issues (most critical first)
        suggestions.sort(key=lambda x: x['count'], reverse=True)
        
        # Round score to one decimal place
        score = round(score, 1)
        
        # Fun messages based on score
        messages = {
            range(0, 4): {
                'title': '😅 Code Health Check',
                'message': "Let's work on improving these areas! Every line of improvement counts! 💪",
                'emoji': '🔨'
            },
            range(4, 7): {
                'title': '🚀 Getting Better!',
                'message': "Good progress! Here are some ways to level up your code! 📈",
                'emoji': '⭐'
            },
            range(7, 9): {
                'title': '🌟 Almost Perfect!',
                'message': "Excellent work! Just a few tweaks to make it shine even brighter! ✨",
                'emoji': '🎯'
            },
            range(9, 11): {
                'title': '🏆 Code Master!',
                'message': "Outstanding! Your code is a masterpiece! Keep up the great work! 🎨",
                'emoji': '👑'
            }
        }

        for score_range, msg in messages.items():
            if int(score) in score_range:
                return {
                    'score': score,
                    'title': msg['title'],
                    'message': msg['message'],
                    'emoji': msg['emoji'],
                    'suggestions': suggestions,
                    'issues': issues[:5]  # Keep top 5 overall issues for reference
                }

    except Exception as e:
        return {
            'score': 5.0,
            'title': '🤔 Analysis Limited',
            'message': "We had some trouble analyzing this one, but keep coding! 🚀",
            'emoji': '⚠️',
            'suggestions': [],
            'issues': [str(e)]
        }

def run_linter(file_path, file_type):
    """Run the appropriate linter and return results"""
    try:
        command = get_linter_command(file_path, file_type)
        if not command:
            return "No linter available for {file_type} files"

        # Special handling for JavaScript files to create a temporary ESLint config
        if file_type == 'js':
            eslint_config = {
                "env": {"browser": True, "es2021": True},
                "extends": "eslint:recommended",
                "parserOptions": {
                    "ecmaVersion": 12,
                    "sourceType": "module"
                }
            }
            with open(os.path.join(os.path.dirname(file_path), '.eslintrc.json'), 'w') as f:
                json.dump(eslint_config, f)

        # Special handling for CSS files to create a temporary Stylelint config
        if file_type == 'css':
            stylelint_config = {
                "extends": "stylelint-config-standard"
            }
            with open(os.path.join(os.path.dirname(file_path), '.stylelintrc.json'), 'w') as f:
                json.dump(stylelint_config, f)

        result = subprocess.run(command, capture_output=True, text=True)
        output = result.stdout or result.stderr
        
        # Clean up temporary config files
        if file_type == 'js':
            os.remove(os.path.join(os.path.dirname(file_path), '.eslintrc.json'))
        if file_type == 'css':
            os.remove(os.path.join(os.path.dirname(file_path), '.stylelintrc.json'))

        return output
    except Exception as e:
        return str(e)

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'file' not in request.files:
        return jsonify({'status': 'error', 'message': 'No file uploaded'})
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'status': 'error', 'message': 'No file selected'})
    
    if not allowed_file(file.filename):
        return jsonify({'status': 'error', 'message': 'File type not supported. Allowed types: .py, .php, .html, .js, .css'})
    
    try:
        file_type = file.filename.rsplit('.', 1)[1].lower()
        
        # Create a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_type}') as temp_file:
            temp_path = temp_file.name
            file.save(temp_path)
            
            # Emit file upload success
            socketio.emit('status_update', {
                'stage': 'upload',
                'message': 'File uploaded successfully'
            })
            time.sleep(0.5)

            # Emit analysis start
            socketio.emit('status_update', {
                'stage': 'analyzing',
                'message': f'Analyzing your {file_type.upper()} masterpiece... 🔍'
            })
            
            # Run analysis
            analysis_result = run_linter(temp_path, file_type)
            
            # Analyze code quality
            quality_result = analyze_code_quality(analysis_result, file_type)
            
            # Clean up the temporary file
            os.unlink(temp_path)
            
            # Emit analysis complete
            socketio.emit('status_update', {
                'stage': 'complete',
                'message': 'Analysis complete',
                'result': analysis_result,
                'quality': quality_result,
                'fileType': file_type
            })
            
            return jsonify({
                'status': 'success',
                'filename': secure_filename(file.filename),
                'analysis': analysis_result,
                'quality': quality_result,
                'fileType': file_type
            })
    
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'Error processing file: {str(e)}'})

if __name__ == '__main__':
    socketio.run(app, debug=True)
