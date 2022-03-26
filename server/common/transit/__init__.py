from server.common.transit.transit import TransitEndpoint

transit_instance = TransitEndpoint()
dispatch = transit_instance.dispatch
register_handler = transit_instance.register
