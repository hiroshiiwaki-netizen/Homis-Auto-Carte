#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PIL/Pillowだけでアイコンを作成"""

from PIL import Image, ImageDraw

def create_icon():
    # 256x256のアイコンを作成
    size = 256
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # おひさまオレンジ色
    orange = (255, 81, 0)
    white = (255, 255, 255)
    light_orange = (255, 119, 51)
    
    # 背景（丸角の四角形）
    draw.rounded_rectangle([8, 8, 248, 248], radius=48, fill=orange)
    
    # カルテ（白い用紙）
    draw.rounded_rectangle([60, 50, 196, 210], radius=8, fill=white)
    
    # クリップ部分
    draw.rounded_rectangle([100, 40, 156, 64], radius=4, fill=(255, 228, 214))
    draw.rounded_rectangle([112, 36, 144, 52], radius=4, fill=orange)
    
    # 心電図ライン（簡略化）
    points = [
        (75, 130), (95, 130), (105, 100), (115, 160), 
        (125, 130), (145, 130), (155, 90), (165, 170), 
        (175, 130), (190, 130)
    ]
    for i in range(len(points) - 1):
        draw.line([points[i], points[i+1]], fill=orange, width=6)
    
    # 自動化ギア
    draw.ellipse([163, 143, 227, 207], fill=light_orange)
    draw.ellipse([175, 155, 215, 195], fill=white)
    draw.ellipse([185, 165, 205, 185], fill=orange)
    
    return img

def main():
    img = create_icon()
    
    # PNGとして保存
    img.save('icon.png', 'PNG')
    print("icon.png を作成しました")
    
    # ICOとして保存（複数サイズ）
    img.save('icon.ico', format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("icon.ico を作成しました！")

if __name__ == "__main__":
    main()
