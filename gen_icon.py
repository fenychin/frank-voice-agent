from PIL import Image, ImageDraw

def create_icon():
    # 生成一个简单的圆形图标（蓝色背景，白色文字 V）
    width = 64
    height = 64
    image = Image.new('RGB', (width, height), (10, 10, 15)) # 匹配项目深色背景
    dc = ImageDraw.Draw(image)
    
    # 画一个发光的圆圈
    dc.ellipse([8, 8, 56, 56], outline=(99, 102, 241), width=4)
    # 画文字 V
    # 由于默认字体可能没有，我们画简单的线条
    dc.line([20, 20, 32, 44], fill=(255, 255, 255), width=4)
    dc.line([32, 44, 44, 20], fill=(255, 255, 255), width=4)
    
    image.save("icon.png")
    return "icon.png"

if __name__ == "__main__":
    create_icon()
