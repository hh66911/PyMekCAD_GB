import numpy as np
from numpy import ndarray
from win32com.client import VARIANT, Dispatch, CDispatch
from pythoncom import VT_ARRAY, VT_R8, VT_DISPATCH, com_error
from enum import Enum


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


def to_xyz(seq):
    length = len(seq)
    if length == 4:
        if not isinstance(seq, ndarray):
            seq = np.array(seq)
        seq = seq / seq[3]
        return (*seq[:3],)
    if length == 3:
        return (*seq,)
    if length == 2:
        return (*seq, 0)
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
        
        print('关闭 WIPEOUT 边框')
        self.doc.SendCommand('wipeout f off ')

    def set_transform(self, tranlation=(0, 0),
                      theta=0., mirrored_y=False, tr=None):
        if tuple(tranlation) == (0, 0) and\
            theta == 0. and not mirrored_y and tr is None:
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
            if len(pts) != 1:
                return (*pts,)
            return pts[0]
        pts_mat = to_vec(*pts, flatten=True)
        pts = (self.transform @ pts_mat.T).T
        if len(pts) != 1:
            return (*pts,)
        return pts[0]

    def zoom_all(self):
        self.doc.Application.ZoomAll()

    def switch_layer(self, ltype=LayerType.SOLID):
        ly = self.doc.Layers.Item(ltype.value)
        self.doc.ActiveLayer = ly

    def arc(self, center, radius, start_angle, end_angle):
        start_angle = np.deg2rad(start_angle)
        end_angle = np.deg2rad(end_angle)
        center = self._transformed_points(center)
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
        try:
            sel = self.doc.SelectionSets.Add('tempset1')
        except com_error:
            sel = self.doc.SelectionSets.Item('tempset1').Delete()
        finally:
            sel = self.doc.SelectionSets.Add('tempset1')
        sel.Select(4,  # most recently created
                   aPoint(pts_off[0]),
                   aPoint(pts_off[1]))
        if sel.Count == 0:
            raise ValueError("Failed to select the any object.")
        wipeout = sel[0]
        if wipeout.ObjectName != 'AcDbWipeout':
            raise ValueError("Selected object is not a wipeout.")
        return wipeout

    def wipeout_rect(self, pt1, pt2):
        x1, y1, z1 = to_xyz(pt1)
        x2, y2, z2 = to_xyz(pt2)
        if z1 != z2:
            raise ValueError('非平面矩形！')
        pts = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
        return self.wipeout(*pts)

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
        pt1, pt2 = self._transformed_points(pt1, pt2)
        pt1, pt2 = pt1[:1], pt2[:2]
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

    def wipeout(self, drawer: Drawer):
        return drawer.wipeout(*self.points)
