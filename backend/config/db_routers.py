class PrimaryReplicaRouter:
    """
    A router to control all database operations on models in the
    application.
    It routes reads to 'replica' and writes to 'default'.
    """

    def db_for_read(self, model, **hints):
        """
        Reads go to a randomly-chosen replica if multiple exist, 
        but we have a single 'replica' configured.
        """
        return 'replica'

    def db_for_write(self, model, **hints):
        """
        Writes always go to primary ('default').
        """
        return 'default'

    def allow_relation(self, obj1, obj2, **hints):
        """
        Relations between objects are allowed if both objects are
        in the primary/replica pool. Since they are the same logical 
        database, we return True.
        """
        db_set = {'default', 'replica'}
        if obj1._state.db in db_set and obj2._state.db in db_set:
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """
        Ensure that we only create tables in the 'default' database.
        The replica is a read-only mirror, so we don't apply migrations to it.
        """
        return db == 'default'
