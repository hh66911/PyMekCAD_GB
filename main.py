#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
    =============================
    Author: DalNur
    Email: liyang@alu.hit.edu.cn
    =============================
"""

from pyautocad import Autocad, APoint
import comtypes.client
import time

acad = Autocad(create_if_not_exists=True)
acad.prompt("Hello! AutoCAD from pyautocad.")
doc = acad.ActiveDocument
print(doc.Name)
msp = doc.ModelSpace

dwgobj = acad.ActiveDocument.Application.Documents.Add("")
dwgobj.Activate()  # 设为当前文件。
doc = acad.ActiveDocument
print(doc.Name)
msp = doc.ModelSpace

# 创建图元
x1, y1 = 0, 0
x2, y2 = 100, 100
p1, p2, = APoint(x1, y1), APoint(x2, y2)
msp.AddLine(p1, p2)

# 文件保存
directory = r"D:"  # 工作目录
dwgname = "ZK.dwg"  # 工作目录
path = directory + "\\" + dwgname
dwgobj.Close(True, path)

# 5.程序退出
acad.ActiveDocument.Application.Quit()
