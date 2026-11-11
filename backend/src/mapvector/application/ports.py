"""Application conveniences resolving replaceable domain ports, never implementations."""
from mapvector.domain.ports import get_ports,DatabasePort

def ProjectDatabase(path):return get_ports().database(path)
def ProjectRepository(path):return get_ports().project_catalog(path)
def load_feature(*args):return get_ports().features.load(*args)
def restore_feature(*args):return get_ports().features.restore(*args)
def update_index(*args):return get_ports().features.update_index(*args)
def sha256_file(*args):return get_ports().files.sha256(*args)
def atomic_json(*args):return get_ports().files.atomic_json(*args)
def atomic_bytes(*args):return get_ports().files.atomic_bytes(*args)
def probe(*args):return get_ports().raster.probe(*args)
def sniff(*args):return get_ports().raster.sniff(*args)
def decode(*args):return get_ports().raster.decode(*args)
def document(*args,**kwargs):return get_ports().editor.document(*args,**kwargs)
def apply_geometry(*args,**kwargs):return get_ports().editor.apply(*args,**kwargs)
def run_process(*args,**kwargs):return get_ports().workers.run(*args,**kwargs)
def worker_is_alive(*args):return get_ports().workers.is_alive(*args)
def write_gis(*args,**kwargs):return get_ports().write_gis(*args,**kwargs)
