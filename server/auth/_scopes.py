class Scopes:
    ME = 'me'

    APP_VIEW = 'app:view'
    APP_CREATE = 'app:create'
    APP_DELETE = 'app:delete'
    APP_MODIFY = 'app:modify'

    EVENTS_RAISE = 'events:raise'
    EVENTS_VIEW = 'events:view'

    ALL = {
        ME,
        APP_VIEW, APP_CREATE, APP_DELETE, APP_MODIFY,
        EVENTS_VIEW,EVENTS_RAISE
    }
