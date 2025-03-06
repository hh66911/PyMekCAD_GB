from enum import Enum
import numpy as np
import matplotlib.pyplot as plt
from scipy.spatial.transform import Rotation
from numpy import ndarray
from matplotlib.patches import Arc, Rectangle
from win32com.client import VARIANT, Dispatch, CDispatch
from pythoncom import VT_ARRAY, VT_R8, VT_DISPATCH
import math
import re
import os
import glob
import pandas as pd
from dataclasses import dataclass


class Angle:
    def __init__(self, degrees):
        # 初始化角度值，以度为单位
        self._degrees = degrees

    def __repr__(self):
        # 输出时只输出角度值
        return f'A({self._degrees})'

    def __str__(self):
        # 字符串表示，输出度分秒
        degrees = self._degrees
        deg = int(degrees)
        minutes = (degrees - deg) * 60
        min = int(minutes)
        seconds = (minutes - min) * 60
        return f"{deg}°{min}'{seconds : <.2f}″"

    def __float__(self):
        # 数字表示，输出角度值
        return float(self._degrees)

    def to_radians(self):
        # 将角度转换为弧度
        return math.radians(self._degrees)

    def sin(self):
        # 计算正弦值
        return math.sin(self.to_radians())

    def cos(self):
        # 计算余弦值
        return math.cos(self.to_radians())

    def tan(self):
        return math.tan(self.to_radians())


def to_xyz(seq):
    length = len(seq)
    if length == 4:
        if not isinstance(seq, ndarray):
            seq = np.array(seq)
        seq = seq / seq[3]
        return *seq[:3],
    if length == 3:
        return *seq,
    if length == 2:
        return *seq, 0
    raise ValueError(
        f"Invalid sequence length. Expected 2, 3, or 4 elements. recieved: {seq}")


def to_vec(*seqs, flatten=True, dim=4, return_split=False):
    def unify_dim(pts: list):
        if dim == 4:
            for i, e in enumerate(pts):
                if len(e) == 3:
                    pts[i] = np.append(e, 1)
                if len(e) == 2:
                    pts[i] = np.append(e, (0, 1))
        else:
            for i, e in enumerate(pts):
                if len(e) == 2:
                    pts[i] = np.append(e, 0)
        return pts

    if flatten:
        pts = (
            list(pt) if isinstance(pt[0], (tuple, list))
            else [pt] for pt in seqs
        )
        if return_split:
            pts_sum, spl_idx = [], []
            for ptg in pts:
                pts_sum.extend(ptg)
                spl_idx.append(len(ptg))
            return np.array(unify_dim(pts)), np.cumsum(spl_idx)
        else:
            return np.array(unify_dim(sum(pts, start=[])))
    else:
        result = []
        for pts in seqs:
            if isinstance(pts[0], (tuple, list)):
                pts = sum((
                    list(pt) if isinstance(pt[0], (tuple, list))
                    else [pt] for pt in pts
                ), start=[])
                result.append(np.array(unify_dim(pts)))
            else:
                result.append(np.array(unify_dim([pts])))
        return result


def aObjs(objs):
    return VARIANT(VT_ARRAY | VT_DISPATCH, objs)


def aPoint(x_or_seq, y=0, z=0):
    if isinstance(x_or_seq, (tuple, list, ndarray)):
        x, y, z = to_xyz(x_or_seq)
    else:
        x = x_or_seq
    return VARIANT(VT_ARRAY | VT_R8, (x, y, z))


def aDouble(xyz):
    if isinstance(xyz, ndarray):
        xyz = xyz.tolist()
    return VARIANT(VT_ARRAY | VT_R8, xyz)


class LayerType(Enum):
    SOLID = 'AM_0'
    DASHED = 'AM_3'
    THIN = 'AM_4'
    DOTTED = 'AM_7'


class HatchType(Enum):
    SOLID = 'SOLID'
    NORMAL = 'ANSI31'


class Drawer:
    def __init__(self, acad=None):
        if acad is None:
            acad = Dispatch("AutoCAD.Application")
        self.doc = acad.ActiveDocument
        self.view = self.doc.ModelSpace
        self.acad_interface = acad
        self.transform = None

    def set_transform(self, tranlation=(0, 0),
                      theta=0., mirrored_y=False, tr=None):
        if tranlation == (0, 0) and theta == 0. and not mirrored_y and tr is None:
            self.transform = None
            return
        if tr is not None:
            self.transform = tr
            return
        tr = get_rotmat(tranlation, theta)
        if mirrored_y:
            mirror_mat = get_mirrormat('y')
            tr = mirror_mat @ tr
        self.transform = tr

    def _transformed_points(self, *pts):
        if self.transform is None:
            return *pts,
        pts_mat = to_vec(*pts, flatten=True)
        pts = (self.transform @ pts_mat.T).T
        if len(pts) != 1:
            return *pts,
        return pts[0]

    def zoom_all(self):
        self.doc.Application.ZoomAll()

    def switch_layer(self, layer_type=LayerType.SOLID):
        ly = self.doc.Layers.Item(layer_type.value)
        self.doc.ActiveLayer = ly

    def arc(self, center, radius, start_angle, end_angle):
        start_angle = np.deg2rad(start_angle)
        end_angle = np.deg2rad(end_angle)
        return self.view.AddArc(aPoint(center), radius, start_angle, end_angle)

    def line(self, pt1, pt2):
        pt1, pt2 = self._transformed_points(pt1, pt2)
        return self.view.AddLine(aPoint(pt1), aPoint(pt2))

    def circle(self, center, radius):
        center = self._transformed_points(center)
        return self.view.AddCircle(aPoint(center), radius)

    def rect(self, pt1, pt2):
        pt1, pt2 = self._transformed_points(pt1, pt2)
        x1, y1, z1 = to_xyz(pt1)
        x2, y2, z2 = to_xyz(pt2)
        if z1 != z2:
            raise ValueError('非平面矩形！')
        pt_seq = sum((
            (x1, y1, z1), (x2, y1, z1),
            (x2, y2, z1), (x1, y2, z1),
            (x1, y1, z1)
        ), start=())
        return self.view.AddPolyline(aDouble(pt_seq))

    def polyline(self, *pts_list):
        pts = sum((
            tuple(pt) if isinstance(pt[0], (tuple, list))
            else (pt,) for pt in pts_list
        ), start=())
        pts = self._transformed_points(*pts)
        pts = sum((
            to_xyz(pt) for pt in pts
        ), start=())
        return self.view.AddPolyline(aDouble(pts))

    def hatch(self, *outer_objs, inner_objs=None,
              hatch_type=HatchType.NORMAL, width=0.5):
        hatch = self.view.AddHatch(0, hatch_type.value, True)
        hatch.ISOPenWidth = width * 100.
        for o in outer_objs:
            if not isinstance(o, (tuple, list)):
                hatch.AppendOuterLoop(aObjs((o,)))
            else:
                hatch.AppendOuterLoop(aObjs(o))
        if inner_objs is None:
            hatch.Evaluate()
            return hatch
        for o in inner_objs:
            if not isinstance(o, (tuple, list)):
                hatch.AppendInnerLoop(aObjs((o,)))
            else:
                hatch.AppendInnerLoop(aObjs(o))
        hatch.Evaluate()
        return hatch

    def random_spline(self, pt1, pt2, min_angle=5, max_angle=10):
        if np.random.rand() < 0.5:
            random_angle = np.random.randint(min_angle, max_angle)
        else:
            random_angle = np.random.randint(-max_angle, -min_angle)
        theta = np.deg2rad(random_angle)
        if len(pt1) > 2:
            pt1 = pt1[:2]
        if len(pt2) > 2:
            pt2 = pt2[:2]
        tang = np.asarray(pt2) - np.asarray(pt1)
        rotation_matrix = np.asarray([
            [np.cos(theta), -np.sin(theta)],
            [np.sin(theta), np.cos(theta)]
        ])
        startTang = (rotation_matrix @ tang).tolist()
        endTang = (rotation_matrix @ tang).tolist()
        startTang = aDouble(startTang + [0])
        endTang = aDouble(endTang + [0])
        pts = aDouble((*pt1, 0, *pt2, 0))
        return self.view.AddSpline(pts, startTang, endTang)


def get_rotmat(translate: tuple, theta: float):
    return np.asarray([
        [np.cos(theta), -np.sin(theta), 0, translate[0]],
        [np.sin(theta), np.cos(theta), 0, translate[1]],
        [0, 0, 1, 0], [0, 0, 0, 1]
    ])  # 齐次变换


def get_mirrormat(axis: str):
    match axis:
        case 'x':
            return np.asarray([
                [1, 0, 0, 0],
                [0, -1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1]
            ])
        case 'y':
            return np.asarray([
                [-1, 0, 0, 0],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1]
            ])
        case 'o':
            return np.asarray([
                [-1, 0, 0, 0],
                [0, -1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1]
            ])
        case _:
            raise ValueError(f'Unsupported axis: {axis}')


class Path2D:
    def __init__(self, start_pos=np.zeros(2)):
        if not isinstance(start_pos, ndarray):
            start_pos = np.array(start_pos)
        self.points = [start_pos]

    def __repr__(self):
        return f'Path2D({self.points})'

    def __str__(self):
        fmt_pts = ' -> '.join([f'({p[0]: .2f}, {p[1]: .2f})' for p in self.points])
        return f'{fmt_pts}'

    def offset(self, x_or_seq, y=None):
        if y is not None:
            off = np.array((x_or_seq, y))
        elif not isinstance(x_or_seq, ndarray):
            off = np.array(x_or_seq)
        else:
            raise ValueError('offset不够')
        self.points.append(self.points[-1] + off)

    def draw(self, drawer: Drawer):
        return drawer.polyline(*self.points)


@dataclass
class DrawedBearing:
    left_border: CDispatch = None
    right_border: CDispatch = None
    left_inner: list[CDispatch] = None
    right_inner: list[CDispatch] = None
    hatch_right: CDispatch = None


class Bearing:
    size_df = pd.read_excel(r"D:\BaiduSyncdisk\球轴承尺寸.xlsx")

    def __init__(self, code):
        self.code = code
        if code.startswith('16'):
            bearing_type = '6'
        else:
            bearing_type = code[0]
        match bearing_type:
            case '7':
                name = '角接触球轴承'
                if code.endswith('AC'):
                    angle = 25
                elif code.endswith('B'):
                    raise ValueError('不支持B型角接触球轴承')
                elif code.endswith('C'):
                    angle = 15
                    code = code[:-1]
                else:
                    raise ValueError('角度信息缺失')
            case '6':
                name = '深沟球轴承'
                angle = None
            case _:
                raise ValueError('不支持的轴承类型')

        code = '7' + self.code[1:]
        codes = Bearing.size_df[["a1", 'a2']]
        idx = codes.stack()[codes.stack() == code]
        idx = list(set(i[0] for i in idx.index))
        if len(idx) > 1:
            raise ValueError(f'错误的型号，多个值找到：{idx}')
        elif len(idx) == 0:
            raise ValueError(f'错误的型号，未找到：{code}')
        size_data = Bearing.size_df.loc[idx[0], :]
        (
            self.d, self.da,
            self.b, self.c,
            self.c1
        ) = size_data[['d', 'D', 'B', 'c', 'c1']]

        self.name = name
        self.angle = np.deg2rad(angle) if angle is not None else 0

    def __repr__(self):
        return f'Bearing({self.code})'

    def __str__(self):
        return f'{self.name} {self.code} {self.d}x{self.da}x{self.b}'

    @staticmethod
    def parse_code_size(digits):
        # 初始化变量
        A = B = C = D = None

        def get_size(d1, d2):
            d = int(d1) * 10 + int(d2)
            if d <= 3:
                d = [10, 12, 15, 17][d]
            else:
                d = d * 5
            return d

        # 匹配五位数字开头的情况：ABCDD
        five_digit_pattern = re.match(r'^(\d)(\d)(\d)(\d)$', digits)
        if five_digit_pattern:
            A, B, C, D1, D2 = five_digit_pattern.groups()
            A, B, C = int(A), int(B), int(C)
            D = get_size(D1, D2)
        # 匹配四位数开头的情况：ABDD
        else:
            four_digit_pattern = re.match(r'^(\d)(\d)(\d)$', digits)
            if four_digit_pattern:
                A, C, D1, D2 = four_digit_pattern.groups()
                A, C = int(A), int(C)
                B = 0 if C != 0 else 1
                D = get_size(D1, D2)
            # 匹配三位数开头并跟随一个斜杠和数值的情况：ABC/D
            else:
                three_digit_with_slash_pattern = re.match(
                    r'^(\d)(\d)/([\d.]+)$', digits)
                if three_digit_with_slash_pattern:
                    A, B, C, D = three_digit_with_slash_pattern.groups()
                    A, B, C = int(A), int(B), int(C)
                    D = float(D)

        # 返回结果
        return A, B, C, D

    def _draw_border(self, drawer: Drawer,
                     left_down: ndarray):
        """
        Draws bearing border with chamfers.
        Default model coordinate is defined as direction='UP';
        origin is left down point of the right rectangle boarder

        Params:
            drawer (object): The drawing tool or context to use for rendering the part.
            left_down (ndarray): The (x, y) coordinates for the left down point of the rect border.
            transform (ndarray): transform matrix

        Returns:
            objs (list[Dispatch])
        """
        length = (self.da - self.d) / 2
        path = Path2D(left_down + np.array((self.c, 0)))
        path.offset(length - self.c * 2, 0)
        path.offset(self.c, self.c)
        path.offset(0, self.b - self.c - self.c1)
        path.offset(-self.c1, self.c1)
        path.offset(self.c + self.c1 - length, 0)
        path.offset(-self.c, -self.c)
        path.offset(0, self.c * 2 - self.b)
        path.offset(self.c, -self.c)
        drawer.switch_layer(LayerType.SOLID)
        return path.draw(drawer)

    def _draw_inner(self, drawer: Drawer,
                    left_down: ndarray,
                    simplified: bool = False,
                    border_objs=None):
        """
        Draws the inner part of the bearing.

        Params:
            drawer (Drawer): The drawing tool or context to use for rendering the part.
            left_down (ndarray): The (x, y) coordinates for the left down point of the border.
            transform (ndarray): Transform matrix.

        Returns:
            objs (list[Dispatch]): List of drawn objects.
        """
        if not isinstance(left_down, ndarray):
            left_down = np.array(left_down, dtype=np.floating)
        length = (self.da - self.d) / 2
        center = left_down + np.array((length / 2, self.b / 2))
        if not simplified:
            drawer.switch_layer(LayerType.SOLID)
            # 非简化画法
            radius = length / 4
            half_b = self.b / 2
            xoff = radius * np.cos(np.pi / 3)
            yoff = radius * np.sin(np.pi / 3)
            points = (
                (-xoff, -half_b), (-xoff, -yoff),  # 左下
                (-xoff, half_b), (-xoff, yoff),  # 左上
                (xoff, -half_b), (xoff, -yoff),  # 右下
                (xoff, yoff),  # 右上
                (xoff + (half_b - yoff) * np.sin(np.deg2rad(33)), half_b)
            ) + center
            points = points.reshape(-1, 2, 2)
            objs = []
            for start, end in points:
                objs.append(drawer.line(start, end))
            objs.append(drawer.circle(center, radius))
            if border_objs is not None:
                aux_arc1 = drawer.arc(center, radius, -60, 60)
                aux_arc2 = drawer.arc(center, radius, 120, 240)
                aux_line1 = drawer.line(points[0][0], points[2][0])
                aux_line2 = drawer.line(points[1][0], points[3][1])
                drawer.switch_layer(LayerType.THIN)
                ht = drawer.hatch(border_objs, inner_objs=[[
                    *objs[:-1], aux_arc1,  aux_arc2, aux_line1, aux_line2
                ]])
                for obj in (aux_arc1, aux_arc2, aux_line1, aux_line2):
                    obj.Delete()
            else:
                ht = None
            return objs, ht
        else:
            drawer.switch_layer(LayerType.THIN)
            angle_vec = np.array((
                np.sin(self.angle) * length / 3,
                np.cos(self.angle) * length / 3
            ))
            vert_angle = self.angle + np.pi / 2
            vert_vec = np.array((
                np.sin(vert_angle) * self.b / 8,
                np.cos(vert_angle) * self.b / 8
            ))
            start = center + angle_vec
            end = center - angle_vec
            objs = [drawer.line(start, end)]
            start = center + vert_vec
            end = center - vert_vec
            objs.append(drawer.line(start, end))
            return objs

    def _draw_side(self, drawer: Drawer,
                   center_pos: ndarray,
                   transform: ndarray):
        mirror_mat = get_mirrormat('y')

        # 画右边的部分
        drawer.set_transform(tr=transform)
        pos = center_pos + np.array((self.d / 2, -self.b / 2))
        rb = self._draw_border(drawer, pos)
        ri, ht = self._draw_inner(drawer, pos,
                                  False, rb)

        # 画左边的部分
        transform = mirror_mat @ transform
        drawer.set_transform(tr=transform)
        lb = self._draw_border(drawer, pos)
        li = self._draw_inner(drawer, pos, True)

        return rb, ri, ht, lb, li

    def draw(self, drawer: Drawer,
             direction: ndarray,
             center_pos: ndarray):
        """
        Draws a part using the specified drawer, direction, and center position.

        Params:
            drawer (object): The drawing tool or context to use for rendering the part.
            direction (tuple): The direction vector in which to draw the part.
            for angular-contact bearings the direction is of its axial direction force;
            for deep grove ball bearings the direction is either of the two directions along the shaft.
            center_pos (tuple): The (x, y) coordinates for the center position of the part.

        Returns:
            objs (list[Dispatch])
        """
        if not isinstance(center_pos, ndarray):
            center_pos = np.array(center_pos, dtype=np.floating)
        if not isinstance(direction, ndarray):
            direction = np.array(direction, dtype=np.floating)

        # get rotation angle from vector
        theta = np.arctan2(direction[1], direction[0]) - np.pi / 2
        transform = get_rotmat(center_pos, theta)

        res = DrawedBearing()

        (
            res.right_border, res.right_inner,
            res.hatch_right,
            res.left_border, res.left_inner
        ) = self._draw_side(drawer, center_pos, transform)

        return res


@dataclass
class DrawedGear:
    right: list[CDispatch] = None
    left: list[CDispatch] = None
    left_hatch: CDispatch = None
    right_hatch: CDispatch = None
    left_axis: CDispatch = None
    right_axis: CDispatch = None


class GearRotation(Enum):
    CLOCKWISE = 1
    COUTER_CLOCKWISE = 2
    NONE = 3


class Gear:
    def __init__(self, module, teeth, bold, d_hole,
                 rot_dir=GearRotation.NONE,
                 beta: Angle = Angle(0)):
        teeth_v = teeth / (beta.cos()**3)
        self.diameter = teeth_v * module
        pitch_diameter = module * teeth_v
        self.r = pitch_diameter / 2
        self.ra = pitch_diameter / 2 + module
        self.rf = pitch_diameter / 2 - 1.25 * module
        self.half_bold = bold / 2
        self.r_hole = d_hole / 2
        self.angle = beta.to_radians()
        self.rotation = rot_dir

    def _draw_half(self, drawer: Drawer, is_second=False):
        bold = self.half_bold * 2

        path = Path2D((self.ra - 1, self.half_bold))
        path.offset(1, -1)
        path.offset(0, 2 - bold)
        path.offset(-1, -1)
        path.offset(0, bold)
        path.offset(1 - self.ra + self.r_hole, 0)
        path.offset(0, -bold)
        path.offset(self.ra - 1 - self.r_hole, 0)
        drawer.switch_layer(LayerType.SOLID)
        objs = [path.draw(drawer)]
        objs.append(drawer.line(
            (self.rf, self.half_bold),
            (self.rf, -self.half_bold)
        ))
        drawer.switch_layer(LayerType.DOTTED)
        axis = drawer.line(
            (self.r, self.half_bold + 3),
            (self.r, -self.half_bold - 3)
        )

        drawer.switch_layer(LayerType.THIN)
        if self.rotation == GearRotation.NONE or is_second:
            aux_rect = drawer.rect(
                (self.r_hole, self.half_bold),
                (self.rf, -self.half_bold)
            )
            hatch = drawer.hatch(aux_rect)
            aux_rect.Delete()
        else:
            width = (self.ra - self.r_hole) / 4
            pt1 = (self.rf - width, self.half_bold)
            pt2 = (self.rf - width, -self.half_bold)
            spl = drawer.random_spline(pt1, pt2)
            aux_pts = [pt1, (self.r_hole, self.half_bold),
                       (self.r_hole, -self.half_bold), pt2]
            aux_polyline = drawer.polyline(aux_pts)
            hatch = drawer.hatch([spl, aux_polyline])
            a1, a2 = width * 1 / 6, width * 1 / 6
            xc = self.rf - width / 2
            match self.rotation:
                case GearRotation.COUTER_CLOCKWISE:
                    objs.append(drawer.line(
                        (xc + a1 / 2 + a2, -self.half_bold),
                        (xc + a1 / 2 - a2, self.half_bold)))
                    objs.append(drawer.line(
                        (xc - a1 / 2 + a2, -self.half_bold),
                        (xc - a1 / 2 - a2, self.half_bold)))
                case GearRotation.CLOCKWISE:
                    objs.append(drawer.line(
                        (xc + a1 / 2 + a2, self.half_bold),
                        (xc + a1 / 2 - a2, -self.half_bold)))
                    objs.append(drawer.line(
                        (xc - a1 / 2 + a2, self.half_bold),
                        (xc - a1 / 2 - a2, -self.half_bold)))

        return objs, hatch, axis

    def draw(self, drawer: Drawer,
             dir_vec: ndarray,
             center_pos: ndarray):
        if not isinstance(center_pos, ndarray):
            center_pos = np.array(center_pos, dtype=np.floating)
        if not isinstance(dir_vec, ndarray):
            dir_vec = np.array(dir_vec, dtype=np.floating)

        # get rotation angle from vector
        theta = np.arctan2(dir_vec[1], dir_vec[0]) - np.pi / 2
        transform = get_rotmat(center_pos, theta)

        res = DrawedGear()

        drawer.set_transform(tr=transform)
        res.right, res.right_hatch, res.right_axis = self._draw_half(
            drawer, False)
        transform = get_mirrormat('y') @ transform
        drawer.set_transform(tr=transform)
        res.left, res.left_hatch, res.left_axis = self._draw_half(
            drawer, True)

        return res


get_R = {
    (0, 3): 0.2, (3, 6): 0.4,
    (6, 10): 0.6, (10, 18): 0.8,
    (18, 30): 1.0, (30, 50): 1.6,
    (50, 80): 2.0, (80, 120): 2.5,
    (120, 180): 3.0, (180, 250): 4.0,
    (250, 320): 5.0, (320, 400): 6.0,
    (400, 500): 8.0, (500, 630): 10,
    (630, 800): 12,  (800, 1000): 16,
    (1000, 1250): 20,  (1250, 1600): 25,
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
