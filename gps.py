#!/usr/bin/env python3
# -*- coding=utf-8 -*-

import os
import csv
import exiftool
import click
from datetime import datetime
import reverse_geocoder as rg
import queue
import threading

# GPS信息二维数组
# (timestamp（float）, latitude, longitude, altitude)
GPS_TABLE = []
# 创建一个队列用于存储文件名
PHOTO_QUEUE = queue.Queue()
# 创建一个锁用于同步输出
PRINT_LOCK = threading.Lock()
# 是否覆盖原文件
OVERWRITE = False
# 照片文件格式
EXT = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".raw", ".cr2", ".arw", ".hif", ".dng", ".nef")


def load_gps_csv(gps_csv_path):
    """从CSV文件中获取GPS信息"""
    global GPS_TABLE
    with open(gps_csv_path, "r") as csvfile:
        reader = csv.reader(csvfile)
        for row in reader:
            try:
                GPS_TABLE.append((float(row[0]), row[1], row[2], row[3]))
            except Exception as e:
                # Skip the header row
                with PRINT_LOCK:
                    click.secho(e, fg="red")
                continue
    GPS_TABLE = set(GPS_TABLE)

def write_gps_csv(gps_csv_path):
    """保存GPS信息到CSV文件"""
    global GPS_TABLE
    GPS_TABLE = set(GPS_TABLE)
    with open(gps_csv_path, "a") as csvfile:
        writer = csv.writer(csvfile)
        for row in GPS_TABLE:
            try:
                writer.writerow(row)
            except Exception as e:
                with PRINT_LOCK:
                    click.secho(e, fg="red")
                continue


def read_photo_gps(photo_path) -> tuple:
    """从图片中获取GPS信息"""
    try:
        with exiftool.ExifToolHelper() as et:
            meta = et.get_metadata(photo_path)[0]
        lon = meta.get("EXIF:GPSLongitude", "")
        lat = meta.get("EXIF:GPSLatitude", "")
        alt = meta.get("EXIF:GPSAltitude", "")
        dt = datetime.strptime(meta.get("EXIF:DateTimeOriginal"), "%Y:%m:%d %H:%M:%S")
        timestamp = dt.timestamp()
        with PRINT_LOCK:
            click.secho(f"{photo_path}: [{dt}] [{lat}, {lon}]")
        return (timestamp, lat, lon, alt)
    except Exception as e:
        with PRINT_LOCK:
            click.secho(f"{photo_path}: [Failed to read EXIF.]", fg="red")
            print(e)
        return ()


def get_closest_gps_row(timestamp) -> tuple:
    """获取时间最接近的GPS信息"""
    closest_gps_row = ()
    min_diff = float("inf")
    for gps_row in GPS_TABLE:
        time_diff = abs(timestamp - gps_row[0])
        if time_diff < min_diff:
            min_diff = time_diff
            closest_gps_row = gps_row

    return min_diff, closest_gps_row


def gps_to_address(lat, lon):
    """Convert GPS coordinates to an address"""
    # 离线GPS转地址
    result = rg.search((lat, lon), verbose=False)[0]
    address = result["cc"] + ", " + result["name"] + ", " + result["admin1"] + ", " + result["cc"]
    return address


def write_photo_gps(photo_path):
    """Add GPS data to an image file"""
    exif_row = read_photo_gps(photo_path)
    # 如果exif获取失败或者已有GPS信息则跳过
    if not exif_row or (exif_row[1] and exif_row[2]):
        return

    # 从CSV中获取GPS信息
    min_diff, gps_row = get_closest_gps_row(exif_row[0])
    if not gps_row:
        return

    timestamp, lat, lon, alt = gps_row
    gps_dt = datetime.fromtimestamp(timestamp)
    address = gps_to_address(lat, lon)

    # 如果最短时间间隔超过1小时则不予采用
    if min_diff > 3600:
        with PRINT_LOCK:
            click.secho(f"Error: {photo_path} Time diff {min_diff} more than 3600. [{gps_dt}]", fg="red")
        return

    with PRINT_LOCK:
        click.secho(f"{photo_path}: [{gps_dt}] [{lat}, {lon}]", fg="yellow")
        click.secho(f"{photo_path}: {address}", fg="yellow")

    with exiftool.ExifToolHelper() as et:
        et.set_tags(
            photo_path,
            {
                "EXIF:GPSLatitude": lat,
                "EXIF:GPSLongitude": lon,
                "EXIF:GPSAltitude": alt,
                "EXIF:GPSLatitudeRef": "N" if float(lat) > 0 else "S",
                "EXIF:GPSLongitudeRef": "E" if float(lon) > 0 else "W",
            },
            params=["-P", "-overwrite_original" if OVERWRITE else ""],
        )
    with PRINT_LOCK:
        click.secho(f"{photo_path}: Done.", fg="green")


def write_worker():
    while True:
        try:
            photo_path = PHOTO_QUEUE.get(block=False)
            try:
                write_photo_gps(photo_path)
            finally:
                PHOTO_QUEUE.task_done()
        except queue.Empty:
            break


def read_worker():
    while True:
        try:
            photo_path = PHOTO_QUEUE.get(block=False)
            try:
                exif_row = read_photo_gps(photo_path)
                if exif_row and exif_row[0] and exif_row[1] and exif_row[2]:
                    GPS_TABLE.append(exif_row)
            finally:
                PHOTO_QUEUE.task_done()
        except queue.Empty:
            break


@click.command()
@click.argument("arg1", type=click.Path())
@click.argument("arg2", type=click.Path())
@click.option("-o", "--overwrite", is_flag=True, default=False, help="Overwrite original image")
@click.option("-t", "--threads", default=4, help="Number of threads to use")
def main(arg1, arg2, overwrite, threads):
    """
    example: python gps.py  <gps_csv> <photos> 将GPS信息写入照片 \n
    example: python gps.py  <photos> <gps_csv> 从照片中获取GPS信息
    """

    OVERWRITE = overwrite

    def process_file(photo_path):
        if photo_path.lower().endswith(EXT) and "thumb" not in photo_path.lower():
            PHOTO_QUEUE.put(photo_path)
        else:
            with PRINT_LOCK:
                click.secho(f"Error: unsupported file format: {photo_path}", fg="red")

    def loop_file(photos_path):
        if os.path.isfile(photos_path):
            process_file(photos_path)
        elif os.path.isdir(photos_path):
            for root, _, files in os.walk(photos_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    process_file(file_path)

    if arg1.lower().endswith(".csv"):
        # 把gps.csv信息写入到photos
        gps_csv_path, photos_path = arg1, arg2
        load_gps_csv(gps_csv_path)
        loop_file(photos_path)

        thread_list = []
        for _ in range(threads):
            t = threading.Thread(target=write_worker)
            t.start()
            thread_list.append(t)
        # 等待所有任务完成
        PHOTO_QUEUE.join()

        # 等待所有线程结束
        for t in thread_list:
            t.join()

    elif arg2.lower().endswith(".csv"):
        # 把photos中的gps信息保存到gps.csv
        gps_csv_path, photos_path = arg2, arg1
        loop_file(photos_path)

        thread_list = []
        for _ in range(threads):
            t = threading.Thread(target=read_worker)
            t.start()
            thread_list.append(t)
        # 等待所有任务完成
        PHOTO_QUEUE.join()

        # 等待所有线程结束
        for t in thread_list:
            t.join()

        write_gps_csv(gps_csv_path)
    else:
        return


if __name__ == "__main__":
    main()
