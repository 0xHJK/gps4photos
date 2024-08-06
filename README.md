# gps4photos

GPS 4 Photos, Code 4 My Life.

批量给照片添加GPS信息

## 使用说明

- 需要安装 `exiftool` 和其他python依赖库
- GPS csv文件格式为 timestamp, latitude, longitude, altitude （时间戳,纬度,精度,高度）

从照片库中批量读取GPS信息保存到csv文件

```bash
python gps.py photos_dir gps.csv
```

从GPS csv中读取最接近的时间的GPS信息写入到照片

```bash
python gps.py gps.csv photos_dir
```

支持单张图片和图片目录，支持多线程（ `-t` 或 `--threads` 指定线程数量）

`-o` 或 `--overwrite` 表示覆盖原来的照片

