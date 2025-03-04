import numpy as np
import matplotlib.pyplot as plt
import numpy as np
from scipy.spatial.transform import Rotation
from numpy.typing import NDArray
from matplotlib.patches import Arc, Rectangle
from win32com.client import VARIANT, Dispatch
from pythoncom import VT_ARRAY, VT_R8, VT_DISPATCH
from enum import Enum
import math


def aObjs(objs):
    return VARIANT(VT_ARRAY | VT_DISPATCH, objs)


def aPoint(x_or_seq, y=0, z=0):
    if isinstance(x_or_seq, tuple):
        if len(x_or_seq) == 2:
            x, y = x_or_seq
        else:
            x, y, z = x_or_seq
    else:
        x = x_or_seq
    return VARIANT(VT_ARRAY | VT_R8, (x, y, z))


def aDouble(xyz):
    return VARIANT(VT_ARRAY | VT_R8, xyz)


class LayerType(Enum):
    SOLID = 'AM_0'
    DASHED = 'AM_3'
    DOTTED = 'AM_7'


class HatchType(Enum):
    SOLID = 'SOLID',
    NORMAL = 'ANSI31'


class Drawer:
    def __init__(self, acad=None):
        if acad is None:
            acad = Dispatch("AutoCAD.Application")
        self.doc = acad.ActiveDocument
        self.view = self.doc.ModelSpace
        self.acad_interface = acad

    def zoom_all(self):
        self.doc.Application.ZoomAll()

    def switch_layer(self, layer_type=LayerType.SOLID):
        ly = self.doc.Layers.Item(layer_type.value)
        self.doc.ActiveLayer = ly

    def arc(self, center, radius, start_angle, end_angle):
        start_angle = np.deg2rad(start_angle)
        end_angle = np.deg2rad(end_angle)
        return self.view.AddArc(aPoint(*center), radius, start_angle, end_angle)

    def line(self, pt1, pt2):
        return self.view.AddLine(aPoint(*pt1), aPoint(*pt2))

    def circle(self, center, radius):
        return self.view.AddCircle(aPoint(*center), radius)

    def rect(self, pt1, pt2):
        x1, y1, x2, y2 = pt1 + pt2
        pt_seq = (
            *pt1, 0, x2, y1, 0,
            *pt2, 0, x1, y2, 0,
            *pt1, 0
        )
        return self.view.AddPolyline(aDouble(pt_seq))

    def hatch(self, *objs, hatch_type=HatchType.NORMAL):
        hatch = self.view.AddHatch(0, hatch_type.value, True)
        obj_lists = []
        for o in objs:
            if isinstance(o, (list, tuple, set, frozenset)):
                obj_lists.extend(o)
            else:
                obj_lists.append(o)
        obj_lists = aObjs(obj_lists)
        hatch.AppendOuterLoop(obj_lists)
        angle = np.deg2rad(angle - 45)
        print(list(hatch.Origin))
        hatch.Rotate(hatch.Origin, angle)
        # rmat = Rotation.from_euler('zxy', [angle, 0, 0]).as_matrix()
        # rmat_np = np.zeros((4, 4))
        # rmat_np[:3, :3] = np.asarray(rmat)
        # rmat_np[-1, -1] = 1
        # rmat = rmat_np.tolist()
        # print(aDouble(rmat))
        # hatch.TransformBy(aDouble(rmat))
        hatch.Evaluate()
        return hatch


class Bearing:
    def __init__(self, code):
        if code[0] != '7' and code[0] != '6':
            raise ValueError('不支持轴承')


class Gear:
    def __init__(self, module, teeth_v, bold):
        self.diameter = teeth_v * module
        pitch_radius = module * teeth_v / 2
        self.d = pitch_radius
        self.df = pitch_radius + module      # 齿顶圆
        self.da = pitch_radius - 1.25*module  # 齿根圆
        self.bold = bold

    def draw(self, drawer):
        pass


get_R = {
    (0, 3): 0.2,
    (3, 6): 0.4,
    (6, 10): 0.6,
    (10, 18): 0.8,
    (18, 30): 1.0,
    (30, 50): 1.6,
    (50, 80): 2.0,
    (80, 120): 2.5,
    (120, 180): 3.0,
    (180, 250): 4.0,
    (250, 320): 5.0,
    (320, 400): 6.0,
    (400, 500): 8.0,
    (500, 630): 10,
    (630, 800): 12,
    (800, 1000): 16,
    (1000, 1250): 20,
    (1250, 1600): 25,
}


class Shaft:
    def __init__(self, initial_diameter=20.0, length=200.):
        self.initial_diameter = initial_diameter
        self.length = length
        self.steps = []          # [(位置, 直径)]
        self.shoulders = []      # [(位置, 高度, 宽度)]
        self.keyways = []        # [(位置, 长度, 宽度)]
        self.gears = []          # [(位置, 宽度, 直径)]

        self.chamfer_radius = 0  # 圆角半径
        for k, v in get_R.items():
            if initial_diameter <= k[1] and initial_diameter > k[0]:
                self.chamfer_radius = v
                break

        self.contour = []        # 原始轮廓
        self.chamfered_contour = []  # 倒角处理后的轮廓

        self.forces = {'y': [], 'z': []}    # 受力 [位置, 数量]
        self.bends = {'y': [], 'z': []}    # 受弯矩 [位置, 数量]
        self.twists = []                    # 受转矩

        self.bearing_pos = []
        self.coupling_pos = None

    def add_bearing(self, position, bearing):
        pass

    def add_step(self, position, diameter):
        self.steps.append((position, diameter))

    def add_shoulder(self, position, height, width):
        self.shoulders.append((position, height, width))

    def add_keyway(self, position, length, width):
        self.keyways.append((position, length, width))

    def add_gear(self, position, width, diameter, fr, ft, fa, bend_plane='z'):
        self.gears.append((position, width, diameter))

    def fix_bearing(self, p1, p2, width=0):
        p1, p2 = p1 + width / 2, p2 + width / 2
        # 计算轴承 y 平面的力
        f_sum = sum(map(lambda x: x[1], self.forces['y']))
        m_sum = sum(map(lambda x: x[0] * x[1], self.forces['y'])) - \
            sum(map(lambda x: x[1], self.bends['y']))
        f1y = (m_sum - p2 * f_sum) / (p1 - p2)
        f2y = f_sum - f1y
        # 计算轴承 z 平面的力
        f_sum = sum(map(lambda x: x[1], self.forces['z']))
        m_sum = sum(map(lambda x: x[0] * x[1], self.forces['z'])) - \
            sum(map(lambda x: x[1], self.bends['z']))
        f1z = (m_sum - p2 * f_sum) / (p1 - p2)
        f2z = f_sum - f1z
        # 添加轴承力
        self.bearing_pos = [p1, p2]

    def _get_diameter_at(self, pos, events):
        """核心方法：获取指定位置的直径"""
        # 按位置排序事件
        sorted_events = sorted(events, key=lambda x: x[0])
        current_diam = self.initial_diameter

        for event_pos, event_diam in sorted_events:
            if event_pos <= pos:
                current_diam = event_diam
            else:
                break  # 已过目标位置，提前终止
        return current_diam

    def process_features(self):
        events = []
        events.append((0, self.initial_diameter))

        # 处理阶梯特征
        current_diam = self.initial_diameter
        for pos, diam in self.steps:
            current_diam += diam
            events.append((pos, current_diam))

        # 转换轴肩特征
        for pos, height, width in self.shoulders:
            current_diam = self._get_diameter_at(pos, events)
            events.append((pos, current_diam + height))
            events.append((pos + width, current_diam))

        # 合并事件点
        events.sort(key=lambda x: x[0])
        merged = []
        last_pos = -np.inf
        for pos, diam in events:
            if pos > last_pos:
                merged.append((pos, diam))
                last_pos = pos
            else:
                merged[-1] = (pos, diam)

        # 生成基础轮廓
        self.contour = []
        current_diam = self.initial_diameter
        current_pos = 0
        self.contour.append((current_pos, current_diam))

        for pos, diam in merged:
            if pos <= current_pos:
                continue
            self.contour.extend([(pos, current_diam), (pos, diam)])
            current_diam = diam
            current_pos = pos

        # 末端延伸
        self.contour.append((self.length, current_diam))

        # 圆角处理
        self._apply_chamfers()

    def _apply_chamfers(self):
        """双圆角处理逻辑"""
        self.chamfered_contour = []

        for i in range(len(self.contour)-1):
            x0, d0 = self.contour[i]
            x1, d1 = self.contour[i+1]

            if x0 == x1:  # 垂直段（直径变化点）
                # 转换为半径单位进行计算
                r0 = d0 / 2
                r1 = d1 / 2
                delta_r = r1 - r0
                abs_radius = abs(self.chamfer_radius)

                # 内圆角（外侧）
                outer_cx = x0 + np.sign(delta_r) * abs_radius
                outer_cy = max(r0, r1) - abs_radius
                if delta_r > 0:
                    outer_theta = np.linspace(np.pi, np.pi / 2, 20)
                else:
                    outer_theta = np.linspace(np.pi / 2, 0, 20)

                # 外圆角（内侧）
                inner_cx = x0 - np.sign(delta_r) * abs_radius
                inner_cy = min(r0, r1) + abs_radius
                if delta_r > 0:
                    inner_theta = np.linspace(-np.pi / 2, 0, 20)
                else:
                    inner_theta = np.linspace(-np.pi, -np.pi / 2, 20)

                # 生成外圆角坐标（直径单位）
                outer_x = outer_cx + abs_radius * np.cos(outer_theta)
                outer_y = (outer_cy + abs_radius * np.sin(outer_theta)) * 2

                # 生成内圆角坐标（直径单位）
                inner_x = inner_cx + abs_radius * np.cos(inner_theta)
                inner_y = (inner_cy + abs_radius * np.sin(inner_theta)) * 2

                self.contour[i+1] = (x1 + abs_radius, d1)

                # 合并并排序坐标点
                if delta_r > 0:
                    combined = sorted(zip(inner_x, inner_y),
                                      key=lambda p: p[0])
                    combined += sorted(zip(outer_x, outer_y),
                                       key=lambda p: p[0])
                else:
                    combined = sorted(zip(outer_x, outer_y),
                                      key=lambda p: p[0])
                    combined += sorted(zip(inner_x, inner_y),
                                       key=lambda p: p[0])
                self.chamfered_contour.extend(combined)
            else:  # 水平段
                self.chamfered_contour.append((x0, d0))

        # 添加轮廓末端
        self.chamfered_contour.append(self.contour[-1])

    def plot(self, cad):
        if not self.chamfered_contour:
            self.process_features()

        fig, ax = plt.subplots(figsize=(12, 4))
        ax.set_aspect('equal')

        # 处理倒角轮廓数据
        x = [p[0] for p in self.chamfered_contour]
        y = [p[1]/2 for p in self.chamfered_contour]  # 转换为半径

        # 绘制轮廓
        ax.plot(x, y, 'b-', lw=1.2, label='Shaft')
        ax.plot(x, [-v for v in y], 'b-', lw=1.2)
        ax.fill_between(x, y, [-v for v in y], color='skyblue', alpha=0.4)

        # 绘制受力
        for pos, val in self.forces['y']:
            draw_dir = (1 if val < 0 else -1) * self.length / 20
            ax.arrow(pos, 0, draw_dir, draw_dir, head_width=2,
                     head_length=4, fc='r', ec='r')
        for pos, val in self.forces['z']:
            draw_dir = (1 if val < 0 else -1) * self.length / 20
            ax.arrow(pos, 0, 0, draw_dir, head_width=2,
                     head_length=4, fc='r', ec='r')

        # 绘制 y 方向的弯矩
        for pos, val in self.bends['y']:
            # 生成圆弧的点
            if val > 0:
                theta = np.linspace(-np.pi / 2, 0, 100)
            else:
                theta = np.linspace(np.pi, np.pi / 2, 100)
            x = pos + 10 * np.cos(theta)
            # 为了区分 y 和 z 方向，将 z 方向的曲线在 y 轴上偏移
            y_offset = -12 if val > 0 else 10
            y = y_offset + 10 * np.sin(theta) / 2
            if val > 0:
                arror_d = (0, 1)
            else:
                arror_d = (1, 0)
            # 根据不同的 z 深度设置不同的颜色透明度，模拟 3D 效果
            alpha = 0.2 + \
                (pos / max([p for p, _ in self.bends['y'] + self.bends['z']])) * 0.8
            ax.plot(x, y, color='r', lw=2, alpha=alpha)
            arrow_start = (x[-1], y[-1])
            ax.arrow(arrow_start[0], arrow_start[1], arror_d[0], arror_d[1],
                     head_width=2, head_length=2, fc='r', ec='r')

        # 绘制 z 方向的弯矩
        for pos, val in self.bends['z']:
            # 生成圆弧的点
            if val > 0:
                theta = np.linspace(-np.pi / 2, 0, 100)
            else:
                theta = np.linspace(np.pi, np.pi / 2, 100)
            x = pos + 10 * np.cos(theta)
            y = 10 * np.sin(theta)
            if val > 0:
                arror_d = (0, 1)
            else:
                arror_d = (1, 0)
            # 根据不同的 z 深度设置不同的颜色透明度，模拟 3D 效果
            alpha = 0.2 + \
                (pos / max([p for p, _ in self.bends['y'] + self.bends['z']])) * 0.8
            ax.plot(x, y, color='r', lw=2, alpha=alpha)
            arrow_start = (x[-1], y[-1])
            ax.arrow(arrow_start[0], arrow_start[1], arror_d[0], arror_d[1],
                     head_width=3, head_length=4, fc='r', ec='r')

        # 绘制半圆形键槽
        for pos, length, width in self.keyways:
            # 绘制上侧线段
            ax.plot([pos, pos + length], [width / 2, width / 2], 'r-', lw=2)
            # 绘制下侧线段
            ax.plot([pos, pos + length], [-width / 2, -width / 2], 'r-', lw=2)

            # 绘制左侧半圆
            left_arc = Arc((pos, 0), width, width, theta1=90,
                           theta2=270, edgecolor='red', lw=2)
            ax.add_patch(left_arc)

            # 绘制右侧半圆
            right_arc = Arc((pos + length, 0), width, width,
                            theta1=-90, theta2=90, edgecolor='red', lw=2)
            ax.add_patch(right_arc)

        # 绘制齿轮
        for pos, width, diameter in self.gears:
            gear = Rectangle((pos, -diameter/2), width,
                             diameter, fc='orange', alpha=0.5)
            ax.add_patch(gear)

        # 绘制联轴器
        if self.coupling_pos is not None:
            coupling = Rectangle((self.coupling_pos - 5, -self.initial_diameter/2),
                                 10, self.initial_diameter, fc='green', alpha=0.5)
            ax.add_patch(coupling)

        plt.title("Improved Shaft Visualization")
        plt.xlabel("X (mm)")
        plt.ylabel("Y (mm)")
        plt.grid(True)
        return fig
