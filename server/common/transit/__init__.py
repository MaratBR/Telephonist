from server.common.transit.transit import TransitEndpoint, mark_handler

transit_instance = TransitEndpoint()
dispatch = transit_instance.dispatch
register_handler = transit_instance.register
