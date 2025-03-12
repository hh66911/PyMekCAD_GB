from enum import Enum
import time
import numpy as np
from numpy import ndarray
from win32com.client import VARIANT, Dispatch
from pythoncom import VT_ARRAY, VT_R8, VT_DISPATCH, com_error
from tenacity import retry, stop_after_attempt, wait_exponential


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
            raise ValueError(f'不支持的轴: {axis}')


def to_xyz(seq):
    length = len(seq)
    if length == 4:
        if not isinstance(seq, ndarray):
            seq = np.array(seq)
        seq = seq / seq[3]
        return (*seq[:3],)
    if length == 3:
        return seq
    if length == 2:
        return (*seq, 0)
    raise ValueError(f"无效的序列长度。预期2、3或4个元素。收到: {seq}")


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
    GLASS = 'ANSI33'
    RUBBER = 'ANSI37'


class Transform:
    def __init__(self, translation=(0, 0),
                 theta=0.0, mirrored_axis=None):
        tr = get_rotmat(translation, theta)
        if mirrored_axis is not None:
            mirror_mat = get_mirrormat(mirrored_axis)
            tr = tr @ mirror_mat
        self.transform = tr
        self.translation = translation
        self.theta = theta
        self.mirrored_axis = mirrored_axis

    def clear(self):
        self.transform = None
        self.theta = 0
        self.mirrored_axis = None
        self.translation = (0, 0)

    def __matmul__(self, other: ndarray):
        if self.transform is None:
            return other
        return self.transform @ other

    def apply_angle(self, angle: float):
        if self.transform is None:
            return angle
        match self.mirrored_axis:
            case 'x':
                angle = -angle
            case 'y':
                angle = np.pi - angle
        return angle + self.theta

    def apply(self, *pts):
        pts_mat = to_vec(*pts, flatten=True)
        return (self.transform @ pts_mat.T).T


class Drawer:
    def __init__(self, acad=None):
        if acad is None:
            acad = Dispatch("AutoCAD.Application")
        self.doc = acad.ActiveDocument
        self.view = self.doc.ModelSpace
        self.selection_sets = self.doc.SelectionSets
        try:
            self.sel = self.selection_sets.Add('__tempset1')
        except com_error:
            self.sel = self.selection_sets.Item('__tempset1')
            self.sel.Clear()
        self.acad_interface = acad
        self.tr_stack: list[Transform] = []

        print('关闭 WIPEOUT 边框')
        self.doc.SendCommand('wipeout f off ')
        print('lt = 0.5')
        self.doc.SendCommand('ltscale 0.5 ')

    def transformed(self, translation=(0, 0),
                    theta=0., mirrored_axis=None, tr=None):
        class TransformControl:
            def __init__(self, s, t):
                self.s = s
                self.t = t

            def __enter__(self):
                self.s.append(self.t)
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                self.s.pop()

        if tr is not None:
            if not isinstance(tr, Transform):
                raise ValueError("提供的变换不是 Transform 的实例。")
            return TransformControl(self.tr_stack, tr)

        return TransformControl(self.tr_stack, Transform(
            translation, theta, mirrored_axis))

    def _transformed_points(self, *pts):
        if len(self.tr_stack) == 0:
            if len(pts) != 1:
                return pts
            return pts[0]
        pts_mat = to_vec(*pts, flatten=True).T
        for tr in reversed(self.tr_stack):
            pts_mat = tr @ pts_mat
        pts = pts_mat.T
        if len(pts) != 1:
            return pts
        return pts[0]

    def _transformed_angles(self, *angles):
        transformed_angles = []
        for angle in angles:
            transformed_angle = angle
            for tr in reversed(self.tr_stack):
                transformed_angle = tr.apply_angle(transformed_angle)
            transformed_angles.append(transformed_angle)
        if len(transformed_angles) == 1:
            return transformed_angles[0]
        return transformed_angles

    def zoom_all(self):
        self.doc.Application.ZoomAll()

    def switch_layer(self, ltype=LayerType.SOLID):
        ly = self.doc.Layers.Item(ltype.value)
        self.doc.ActiveLayer = ly

    def arc(self, center, radius, start_angle, end_angle):
        start_angle = np.deg2rad(start_angle)
        end_angle = np.deg2rad(end_angle)
        center = self._transformed_points(center)
        start_angle, end_angle = self._transformed_angles(
            start_angle, end_angle)
        start_angle, end_angle = sorted((start_angle, end_angle))
        return self.view.AddArc(aPoint(center), radius, start_angle, end_angle)

    def line(self, pt1, pt2):
        pt1, pt2 = self._transformed_points(pt1, pt2)
        return self.view.AddLine(aPoint(pt1), aPoint(pt2))

    def circle(self, center, radius):
        center = self._transformed_points(center)
        return self.view.AddCircle(aPoint(center), radius)

    def rect(self, pt1, pt2):
        x1, y1, z1 = to_xyz(pt1)
        x2, y2, z2 = to_xyz(pt2)
        if z1 != z2:
            raise ValueError('非平面矩形！')
        pt12 = (x1, y2, z1)
        pt21 = (x2, y1, z1)
        pt1, pt2, pt12, pt21 = self._transformed_points(pt1, pt2, pt12, pt21)
        pt_seq = sum((
            to_xyz(pt) for pt in (pt1, pt12, pt2, pt21, pt1)
        ), start=())
        return self.view.AddPolyline(aDouble(pt_seq))

    def hexagonal(self, center, a, angle):
        angle_offset = np.deg2rad(angle)
        points = []
        for i in range(6):
            theta = angle_offset + i * np.pi / 3
            x = center[0] + a * np.cos(theta)
            y = center[1] + a * np.sin(theta)
            points.append((x, y))
        points.append(points[0])  # Close the hexagon
        points = self._transformed_points(*points)
        points = sum((to_xyz(pt) for pt in points), ())
        return self.view.AddPolyline(aDouble(points))

    def circle3(self, pt1, pt2, pt3):
        x1, y1, z1 = to_xyz(pt1)
        x2, y2, z2 = to_xyz(pt2)
        x3, y3, z3 = to_xyz(pt3)
        if z1 != z2 or z1 != z3:
            raise ValueError('非平面圆！')
        # calc center:
        a = 2 * (x2 - x1)
        b = 2 * (y2 - y1)
        c = x2 ** 2 + y2 ** 2 - x1 ** 2 - y1 ** 2
        d = 2 * (x3 - x1)
        e = 2 * (y3 - y1)
        f = x3 ** 2 + y3 ** 2 - x1 ** 2 - y1 ** 2
        x = (b * f - e * c) / (b * d - e * a)
        y = (d * c - a * f) / (b * d - e * a)
        # calc radius:
        r = np.sqrt((x - x1) ** 2 + (y - y1) ** 2)
        return self.circle((x, y, z1), r)

    def arc3(self, p1, p2, p3, direction='clockwise'):
        """
        使用三点坐标计算圆心，并得到按一定旋转方向包含这三点的弧的起始角度和终止角度。

        参数:
        p1, p2, p3 : tuple
            三个点的坐标，每个点是一个元组 (x, y)。
        direction : str, optional
            旋转方向，'clockwise' 表示顺时针，'counterclockwise' 表示逆时针。默认为 'clockwise'。

        返回:
        center : tuple
            圆心坐标 (x, y)。
        start_angle, end_angle : float
            弧的起始角度和终止角度，单位为弧度。
        """

        # 计算圆心坐标
        A = p2[0] - p1[0]
        B = p2[1] - p1[1]
        C = p3[0] - p1[0]
        D = p3[1] - p1[1]
        E = A * (p1[0] + p2[0]) + B * (p1[1] + p2[1])
        F = C * (p1[0] + p3[0]) + D * (p1[1] + p3[1])
        G = 2 * (A * (p3[1] - p2[1]) - B * (p3[0] - p2[0]))

        if G == 0:
            raise ValueError("三点共线，无法确定圆心")

        center_x = (D * E - B * F) / G
        center_y = (A * F - C * E) / G
        center = (center_x, center_y)
        # print(center, p1, p2, p3)

        # 计算每个点相对于圆心的角度
        def get_angle(point):
            dx = point[0] - center[0]
            dy = point[1] - center[1]
            return np.arctan2(dy, dx)

        angles = sorted([get_angle(p1), get_angle(p2), get_angle(p3)])

        # 确定弧的起始角度和终止角度
        if direction == 'clockwise':
            start_angle, end_angle = angles[-1], angles[0]
        elif direction == 'counterclockwise':
            start_angle, end_angle = angles[0], angles[-1]
        else:
            raise ValueError("无效的旋转方向")

        return self.arc(center, np.linalg.norm(np.array(p1) - np.array(center)),
                        np.rad2deg(start_angle), np.rad2deg(end_angle))

    def polyline(self, *pts_list):
        pts = sum((
            tuple(pt) if isinstance(pt[0], (tuple, list, ndarray))
            else (pt,) for pt in pts_list
        ), start=())
        if len(pts) < 2:
            raise ValueError('过少的点')
        pts = self._transformed_points(*pts)
        pts = sum((
            to_xyz(pt) for pt in pts
        ), start=())
        return self.view.AddPolyline(aDouble(pts))

    @retry(stop=stop_after_attempt(5),
           wait=wait_exponential(multiplier=1, min=1, max=10))
    def _select_recent(self, pt1, pt2, objname=None):
        self.sel.Clear()
        time.sleep(0.02)
        self.sel.Select(4,  # most recently created
                        aPoint(pt1),
                        aPoint(pt2))
        time.sleep(0.02)
        if self.sel.Count == 0:
            raise ValueError("选择对象失败。")
        sel = self.sel[0]
        if objname is None:
            return sel
        time.sleep(0.02)
        if sel.ObjectName != objname:
            raise ValueError(f"选择的对象不是 {objname}.")

    def wipeout(self, *pts_list):
        pts = sum((
            tuple(pt) if isinstance(pt[0], (tuple, list))
            else (pt,) for pt in pts_list
        ), start=())
        pts_off = self._transformed_points(*pts)
        pts_off = tuple((to_xyz(pt)[:2] for pt in pts_off))
        command = 'WIPEOUT ' + ' '.join([
            f'{x:.10e},{y:.10e}' for x, y in pts_off]) + '  '
        # print(command)
        self.doc.SendCommand(command)
        return self._select_recent(
            pts_off[0], pts_off[1], 'AcDbWipeout')

    def wipeout_rect(self, pt1, pt2):
        x1, y1, z1 = to_xyz(pt1)
        x2, y2, z2 = to_xyz(pt2)
        if z1 != z2:
            raise ValueError('非平面矩形！')
        pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        return self.wipeout(*pts)

    def hatch(self, *outer_objs, inner_objs=None,
              hatch_type=HatchType.NORMAL, width=1):
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
        pt1, pt2 = self._transformed_points(pt1, pt2)
        pt1, pt2 = pt1[:2], pt2[:2]
        tang = pt2 - pt1
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

    def update(self):
        self.doc.Regen(0)


class Arc2D:
    def __init__(self, c, r, a1, a2, is_rad=False):
        self.c = c
        self.a1 = np.rad2deg(a1) if is_rad else a1
        self.a2 = np.rad2deg(a2) if is_rad else a2
        self.r = r
        self.end = self.c + self.r * np.array((
            np.cos(np.deg2rad(self.a2)),
            np.sin(np.deg2rad(self.a2))
        ))

    def to_pts(self, num=10):
        angles = np.deg2rad(np.linspace(self.a1, self.a2, num=num))
        points = self.r * np.vstack((np.cos(angles), np.sin(angles))).T + self.c
        return points.tolist()

    def draw(self, drawer: Drawer):
        return drawer.arc(self.c, self.r,
                          self.a1, self.a2)


class Path2D:
    def __init__(self, start_pos=np.zeros(2)):
        if not isinstance(start_pos, ndarray):
            start_pos = np.array(start_pos)
        self.points = [start_pos]
        self.temp_pos = None

    def __repr__(self):
        return f'Path2D({self.points})'

    def __str__(self):
        fmt_pts = ' -> '.join([f'({p[0]: .2f}, {p[1]: .2f})' for p in self.points])
        return f'{fmt_pts}'
    
    def offset(self, x_or_seq, y=None):
        off = None
        if y is not None:
            off = np.array((x_or_seq, y))
        elif not isinstance(x_or_seq, ndarray):
            if len(x_or_seq) < 2:
                raise ValueError('offset维数不对')
            off = np.array(x_or_seq)
            
        if self.temp_pos is None:
            self.points.append(self.points[-1] + off)
            return self.points[-1]
        else:
            self.temp_pos = self.temp_pos + off
            return self.temp_pos

    def goto(self, x_or_seq, y=None):
        pt = None
        if y is not None:
            pt = np.array((x_or_seq, y))
        elif not isinstance(x_or_seq, ndarray):
            pt = np.array(x_or_seq)
        else:
            pt = x_or_seq
        if len(pt) < 2:
            raise ValueError('point维数不对')
        if self.temp_pos is None:
            self.points.append(pt)
            return self.points[-1]
        else:
            self.temp_pos = pt
            return self.temp_pos

    def draw(self, drawer: Drawer):
        if len(self.points) == 2:
            return drawer.line(*self.points)
        result = []
        pts = []
        for p in self.points:
            if isinstance(p, Arc2D):
                if len(pts) > 0:
                    if len(pts) == 2:
                        result.append(drawer.line(pts[0], pts[1]))
                    elif len(pts) > 2:
                        result.append(drawer.polyline(pts))
                    pts.clear()
                result.append(p.draw(drawer))
                # pts.append(p.end)
            else:
                pts.append(p)
        if len(pts) > 1:
            if len(pts) == 2:
                result.append(drawer.line(pts[0], pts[1]))
            else:
                result.append(drawer.polyline(pts))
        return result

    def wipeout(self, drawer: Drawer):
        points = sum((
            p.to_pts() if isinstance(p, Arc2D) else [p]
            for p in self.points
        ), start=[])
        return drawer.wipeout(*points)

    def arc(self, r, angle, is_left=True, tang=None):
        if len(self.points) < 2:
            raise ValueError('不够一条线')
        vec = np.array((0, 0, 1))
        vec = vec if is_left else -vec
        if tang is None:
            tang = self.points[-1] - self.points[-2]
        tang = to_vec(tang, dim=3)
        vecr = np.cross(vec, tang)[0]
        vecr = vecr / np.linalg.norm(vecr)
        cen = self.points[-1] + vecr[:2] * r
        t0 = np.arctan2(-vecr[1], -vecr[0])
        t1 = t0 + np.deg2rad(angle if is_left else -angle)
        self.points.append(Arc2D(cen, r, t0, t1, True))
        self.points.append(cen + (r * np.cos(t1), r * np.sin(t1)))
        return self.points[-1]

    def up(self):
        if self.temp_pos is None:
            self.temp_pos = self.points[-1]
        else:
            raise ValueError('已经抬笔了')
        return self.temp_pos

    def down(self):
        if self.temp_pos is None:
            raise ValueError('笔未抬起')
        if self.temp_pos != self.points[-1]:
            self.points.append(self.temp_pos)
        self.temp_pos = None