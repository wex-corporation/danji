#!/bin/bash
# 드롭·훅·엔딩에 쓰는 무료 영상(Mixkit)을 9:16으로 잘라 30fps 프레임으로 뽑는다.
# 인자: 이름 클립ID 시작초 길이초 가로중심(0~1)
set -e
FF=$(python3 -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
cd "$(dirname "$0")"
mkdir -p build/clips build/frames
cd build
# 클립 받기(Mixkit 무료 라이선스)
for id in 22015 22827 47957 48922 12854 21788 48795 5886 50726 40656 30113 12877 9686 30146; do
  [ -s clips/$id.mp4 ] || curl -sS --max-time 120 -o clips/$id.mp4 "https://assets.mixkit.co/videos/$id/$id-1080.mp4"
  [ $(stat -c%s clips/$id.mp4) -gt 10000 ] || curl -sS --max-time 120 -o clips/$id.mp4 "https://assets.mixkit.co/videos/$id/$id-720.mp4"
done
cut() {
  name=$1; id=$2; ss=$3; dur=$4; cx=$5
  rm -rf frames/$name; mkdir -p frames/$name
  # 세로 원본이면 그대로, 가로면 높이 기준 9:16 창을 cx 위치에서 자른다. 1.1배로 뽑아 켄번즈 여유를 둔다
  $FF -hide_banner -loglevel error -ss $ss -i clips/$id.mp4 -t $dur \
    -vf "fps=30,crop='if(gt(iw/ih,9/16),ih*9/16,iw)':'if(gt(iw/ih,9/16),ih,iw*16/9)':'if(gt(iw/ih,9/16),(iw-ih*9/16)*$cx,0)':0,scale=1188:2112:flags=lanczos" \
    -q:v 3 frames/$name/%03d.jpg
  echo "$name $(ls frames/$name | wc -l)"
}
cut hook_mail 22015 6.0 0.8 0.97
cut w_fee     22827 2.0 0.6 0.45
cut w_park    47957 5.0 0.6 0.5
cut w_guard   48922 4.0 0.6 0.62
cut w_lift    12854 0.3 0.6 0.66
cut w_recycle 21788 10.0 0.6 0.42
cut w_play    48795 5.0 0.6 0.38
cut w_school  5886 4.0 0.6 0.7
cut w_lib     50726 1.0 0.6 0.5
cut w_walk    40656 3.0 0.6 0.5
cut w_han     30113 1.0 0.6 0.55
cut w_key     12877 0.4 0.6 0.5
cut w_build   9686 10.0 0.6 0.45
cut end_city  30146 7.0 2.1 0.62
