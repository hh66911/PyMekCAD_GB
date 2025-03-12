import pythoncom
import win32com.client
import math
import re
import numpy as np
import pandas as pd
import time
import winsound

wincad = win32com.client.Dispatch("AutoCAD.Application")
doc = wincad.ActiveDocument
doc.Utility.Prompt("Hello! Autocad from pywin32com.\n")
msp = doc.ModelSpace

from drawer import Drawer, LayerType

def draw_talbe(drawer: Drawer, data, start_point, width, height):
    x = np.cumsum([start_point[0]] + width)
    y = np.cumsum([start_point[1]] + height)
    drawer.switch_layer(LayerType.thii)
    for i in range(len(x)):
        drawer.line((x[i], y[0]), (x[i], y[-1]))
    for i in range(len(y)):
        drawer.line((x[0], y[i]), (x[-1], y[i]))
    for i, r in enumerate(data):
        if r is None:
            continue
        for j, cell in enumerate(r):
            center = ((x[j] + x[j + 1]) / 2, (y[i] + y[i + 1]) / 2)
            if cell is not None and len(cell) > 0:
                drawer.text(center, str(cell))


title = '中间轴'
title_en = 'H2-2'
name = '黄新航'
material = '调质45#'
ratio = '1 : 2'
aff = '中国农业大学工学院'
dtime = '25.3.10'


drawer = Drawer(wincad)

data = [
    ['标记', '处数', '分区', '更改文号', '签名', '年月日'],
]

start_point = (0, 28)
width = [10, 10, 16, 16, 12, 16]
height = [7] * 4

draw_talbe(drawer, data,
           start_point, width, height)


data = [
    ['工艺', None, None, '批准', None, None],
    ['审核', None, None, None, None, None],
    None,
    ['设计', name, f'        {dtime}', '标准化', '（签名）', '（年月日）'],
]

start_point = (0, 0)
width = [12, 12, 16, 12, 12, 16]
height = [7] * 4

draw_talbe(drawer, data,
           start_point, width, height)


start_point = (sum(width), 9)
width = [6.5] * 4 + [12] * 2
height = [9]
draw_talbe(drawer, [[None] * 4 + [None, f'       {ratio}']],
           start_point, width, height)

start_point = (start_point[0], 0)
width = [50]
height = [9]
draw_talbe(drawer, [['共1张 第1张']],
           start_point, width, height)

start_point = (start_point[0], 18)
width = [26, 12, 12]
height = [10]
draw_talbe(drawer, [['阶段标记', '重量', '比例']],
           start_point, width, height)

start_point = (start_point[0], 28)
width = [50]
height = [28]
draw_talbe(drawer, [[material]],
           start_point, width, height)

start_point = (start_point[0] + sum(width), 0)
width = [180 - start_point[0]]
height = [18, 20, 18]
draw_talbe(drawer, [[title_en], [title], [aff]],
           start_point, width, height)

drawer.update()