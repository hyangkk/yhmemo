# Tapo CCTV RTSP 영상 가로채기

## 작동 구조

```
[Tapo 카메라] --RTSP(TCP/554)--> [공유기(172.30.1.x)] ---> [이 맥북]
   172.30.1.79                     thenaeun-5G              ffmpeg/python
```

### 원리
1. Tapo 카메라는 RTSP(Real Time Streaming Protocol) 서버를 내장하고 있음
2. 같은 WiFi(공유기) 네트워크에 연결된 장비는 RTSP URL로 직접 스트림 수신 가능
3. ffmpeg가 RTSP 클라이언트 역할을 하여 카메라의 영상 스트림을 받아옴
4. 받아온 스트림을 파일 저장(녹화), 스냅샷, HLS 변환 등으로 활용

### RTSP URL 형식
```
rtsp://사용자:비밀번호@카메라IP:554/stream1  (고화질)
rtsp://사용자:비밀번호@카메라IP:554/stream2  (저화질)
```

## 사전 준비

1. **Tapo 앱에서 카메라 계정 설정** (필수!)
   - Tapo 앱 → 카메라 설정 → 고급 설정 → 카메라 계정
   - 사용자명/비밀번호 설정 (이것이 RTSP 접속 계정)

2. **같은 네트워크 연결**
   - 맥북과 카메라가 같은 공유기(thenaeun-5G)에 연결되어 있어야 함

3. **필수 패키지**
   ```bash
   # macOS
   brew install ffmpeg
   pip3 install opencv-python-headless

   # Linux
   apt install ffmpeg
   pip3 install opencv-python-headless
   ```

## 사용법

### 1. 연결 테스트
```bash
cd scripts/tapo-rtsp
python3 check_stream.py
```

### 2. 영상 녹화
```bash
# 기본 60초 녹화
python3 capture.py record

# 5분 녹화
python3 capture.py record --duration 300

# 저화질로 녹화 (용량 절약)
python3 capture.py record --low
```

### 3. 스냅샷 캡처
```bash
# 1장 캡처
python3 capture.py snapshot

# 10초 간격으로 5장 연속 캡처
python3 capture.py snapshot --interval 10 --count 5
```

### 4. HLS 실시간 스트리밍
```bash
# HLS로 변환 (웹 브라우저에서 시청 가능)
python3 capture.py hls
```

### 5. 모션 감지 녹화
```bash
# 움직임 감지되면 자동 녹화
python3 motion_detect.py

# 민감도 조절 (낮을수록 민감)
python3 motion_detect.py --sensitivity 20 --min-area 300
```

## 파일 구조
```
scripts/tapo-rtsp/
├── config.py          # 카메라 접속 설정
├── check_stream.py    # 연결 테스트
├── capture.py         # 녹화/스냅샷/HLS
├── motion_detect.py   # 모션 감지 자동 녹화
├── recordings/        # 녹화 파일 저장 (자동 생성)
├── snapshots/         # 스냅샷 저장 (자동 생성)
└── hls/               # HLS 세그먼트 (자동 생성)
```
