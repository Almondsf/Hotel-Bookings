from rest_framework import generics
from .models import RoomType, Room
from .serializers import RoomTypeSerializer, RoomSerializer
from rest_framework.response import Response
from rest_framework import status

class RoomTypeCreateView(generics.CreateAPIView):
    
    serializer_class = RoomTypeSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        room_type = serializer.save()
        return Response(
            RoomTypeSerializer(room_type).data, 
            status=status.HTTP_201_CREATED
        )
class RoomCreateView(generics.CreateAPIView):
    serilalizer_class = RoomSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        room = serializer.save()
        return Response(
            RoomSerializer(room).data,
            status=status.HTTP_201_CREATED
        )