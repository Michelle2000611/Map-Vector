class CommandConflict(Exception):
    """Structured domain/application rejection that rolls back the current command."""
    def __init__(self,code:str,detail:dict|None=None):
        self.code=code
        self.detail=detail or {}
        super().__init__(code)
