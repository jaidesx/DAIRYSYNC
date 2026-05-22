from .models import Alert


def active_alerts(request):
    if not request.user.is_authenticated:
        return {'active_alerts': 0}
    return {'active_alerts': Alert.objects.filter(resolved=False).count()}
