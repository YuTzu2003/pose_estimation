import os
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'mp4', 'mov', 'avi'}

# 確保上傳資料夾存在
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    if 'video' not in request.files:
        return jsonify({'error': '未上傳影片'}), 400
    
    file = request.files['video']
    if file.filename == '':
        return jsonify({'error': '未選擇檔案'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # 獲取參數
        shoes_length = request.form.get('shoes_length', type=float)
        img_pixel = request.form.get('img_pixel', type=int)
        features = request.form.getlist('features')

        # 這裡未來會串接分析邏輯
        # 模擬回傳結果
        result = {
            'status': 'success',
            'filename': filename,
            'params': {
                'shoes_length': shoes_length,
                'img_pixel': img_pixel,
                'features': features
            },
            'analysis': {
                'avg_spm': 175,
                'stride_cm': 120,
                'symmetry': 98.5
            }
        }
        return jsonify(result)

    return jsonify({'error': '不支援的檔案格式'}), 400

if __name__ == '__main__':
    app.run(debug=True, port=5000)
