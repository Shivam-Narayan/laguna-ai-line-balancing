import pytest
from config.db_routers import PrimaryReplicaRouter

class MockModel:
    pass

def test_db_for_read():
    router = PrimaryReplicaRouter()
    # Should route reads to replica
    assert router.db_for_read(MockModel) == 'replica'

def test_db_for_write():
    router = PrimaryReplicaRouter()
    # Should route writes to default
    assert router.db_for_write(MockModel) == 'default'

def test_allow_relation():
    router = PrimaryReplicaRouter()
    
    class MockState:
        def __init__(self, db):
            self.db = db
            
    class MockInstance:
        def __init__(self, db):
            self._state = MockState(db)

    obj1 = MockInstance('default')
    obj2 = MockInstance('replica')
    obj3 = MockInstance('other_db')

    # Should allow relations between default and replica
    assert router.allow_relation(obj1, obj2) is True
    # Should return None if any object is not in default/replica
    assert router.allow_relation(obj1, obj3) is None

def test_allow_migrate():
    router = PrimaryReplicaRouter()
    # Migrations should only run on default
    assert router.allow_migrate('default', 'some_app', 'MockModel') is True
    assert router.allow_migrate('replica', 'some_app', 'MockModel') is False
