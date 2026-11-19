"""Read-only color comparison of every active face in the current asset."""
import math
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from mapvector.domain.commands import UUIDString
from mapvector.domain.errors import CommandConflict


class FaceColorRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    asset_id: UUIDString
    base_revision: int = Field(ge=0, le=9007199254740990, strict=True)
    source_feature_id: UUIDString
    mode: Literal['exact', 'similar'] = 'similar'
    tolerance: float = Field(default=15, ge=0, le=100, strict=True)


class FaceColorMatch(BaseModel):
    feature_id: UUIDString
    fill_color: str = Field(pattern='^#[0-9a-f]{6}$')
    delta_e: float = Field(ge=0, allow_inf_nan=False)
    match_type: Literal['exact', 'similar']


class FaceColorReport(BaseModel):
    asset_id: UUIDString
    base_revision: int
    source_feature_id: UUIDString
    source_color: str = Field(pattern='^#[0-9a-f]{6}$')
    mode: Literal['exact', 'similar']
    tolerance: float = Field(ge=0, le=100, allow_inf_nan=False)
    scanned_face_count: int = Field(ge=0)
    invalid_color_count: int = Field(ge=0)
    match_count: int = Field(ge=0)
    matches: list[FaceColorMatch]


def _normalized_color(value):
    return value.lower() if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value) else None


def _srgb_to_lab(color):
    """IEC sRGB, D65 (x=.3127, y=.3290), and the CIE 1976 Lab transform."""
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    red, green, blue = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                        for value in channels]
    # High precision sRGB-to-XYZ matrix for the D65 reference white.
    x = .41239079926595934 * red + .357584339383878 * green + .1804807884018343 * blue
    y = .21263900587151027 * red + .715168678767756 * green + .07219231536073371 * blue
    z = .01933081871559185 * red + .11919477979462598 * green + .9505321522496607 * blue
    def transform(value):
        return value ** (1 / 3) if value > (6 / 29) ** 3 else value / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = (transform(x / .9504559270516716), transform(y), transform(z / 1.0890577507598784))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def search(database, project_id, request: FaceColorRequest):
    # All identities and persisted effective fill colors share one SQLite snapshot.
    # The read-only database connection also prevents accidental business writes.
    with database.read() as connection:
        connection.execute('BEGIN')
        project = connection.execute('SELECT working_revision,current_asset_id FROM project WHERE project_id=?',
                                     (project_id,)).fetchone()
        if project is None:
            raise KeyError(project_id)
        if project['working_revision'] != request.base_revision:
            raise CommandConflict('REVISION_CONFLICT', {'working_revision': project['working_revision']})
        if project['current_asset_id'] != request.asset_id or connection.execute(
                'SELECT asset_id FROM asset WHERE asset_id=? AND project_id=?',
                (request.asset_id, project_id)).fetchone() is None:
            raise CommandConflict('ASSET_RESULT_MISMATCH')
        # Style commands persist the effective face fill, including overrides, here.
        # Geometry, raster files, model artifacts, and preview/history tables are unused.
        faces = connection.execute("""SELECT f.feature_id,a.fill_color FROM feature f
            LEFT JOIN face_attribute a USING(feature_id)
            WHERE f.project_id=? AND f.asset_id=? AND f.feature_type='face'
            AND f.lifecycle_status='active'""", (project_id, request.asset_id)).fetchall()

    source = next((row for row in faces if row['feature_id'] == request.source_feature_id), None)
    if source is None:
        raise CommandConflict('SELECTION_SCOPE_INVALID')
    source_color = _normalized_color(source['fill_color'])
    if source_color is None:
        raise CommandConflict('FACE_COLOR_INVALID', {'feature_id': request.source_feature_id})

    tolerance = 0 if request.mode == 'exact' else request.tolerance
    source_lab = _srgb_to_lab(source_color) if request.mode == 'similar' else None
    delta_by_color = {source_color: 0.0}
    invalid_color_count = 0
    matches = []
    for row in faces:
        color = _normalized_color(row['fill_color'])
        if color is None:
            invalid_color_count += 1
            continue
        if color not in delta_by_color:
            delta_by_color[color] = math.dist(source_lab, _srgb_to_lab(color)) if source_lab is not None else None
        delta = delta_by_color[color]
        if delta is not None and delta <= tolerance:
            matches.append({'feature_id': row['feature_id'], 'fill_color': color, 'delta_e': delta,
                            'match_type': 'exact' if color == source_color else 'similar'})
    matches.sort(key=lambda item: (item['delta_e'], item['feature_id']))
    return {'asset_id': request.asset_id, 'base_revision': request.base_revision,
            'source_feature_id': request.source_feature_id, 'source_color': source_color,
            'mode': request.mode, 'tolerance': tolerance, 'scanned_face_count': len(faces),
            'invalid_color_count': invalid_color_count, 'match_count': len(matches), 'matches': matches}
