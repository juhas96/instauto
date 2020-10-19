import json
import hmac
import time
import uuid

from requests import Session, Response
from typing import Callable, Union, Optional
from instauto.api.actions.stubs import _request

from ..structs import Method, State, DeviceProfile, IGProfile, PostLocation
from .structs.post import PostFeed, PostStory, Comment, UpdateCaption, Save, Like, Unlike, Device,\
    RetrieveByUser, Location, PostFeedVideo
from ..exceptions import BadResponse

from .helpers import build_default_rupload_params, get_image_type, remove_from_dict


class PostMixin:
    """Handles everything related to Instagram posts."""
    _session: Session
    ig_profile: IGProfile
    state: State
    device_profile: DeviceProfile
    _request: _request
    _gen_uuid: Callable
    _generate_user_breadcrumb: Callable

    breadcrumb_private_key: bytes
    bc_hmac: hmac.HMAC

    def _post_act(self, obj: Union[Save, Comment, UpdateCaption, Like, Unlike]):
        """Peforms the actual action and calls the Instagram API with the data provided."""
        if obj.feed_position is None:
            delattr(obj, 'feed_position')

        endpoint = f'media/{obj.media_id}/{obj.action}/'
        return self._request(endpoint, Method.POST, data=obj.__dict__, signed=True)

    def post_like(self, obj: Like) -> Response:
        """Likes a post"""
        return self._post_act(obj)

    def post_unlike(self, obj: Unlike) -> Response:
        """Unlikes a post"""
        return self._post_act(obj)

    def post_save(self, obj: Save) -> Response:
        """Saves a post to your Instagram account"""
        return self._post_act(obj)

    def post_comment(self, obj: Comment) -> Response:
        """Comments on a post"""
        return self._post_act(obj)

    def post_update_caption(self, obj: UpdateCaption) -> Response:
        """Updates the caption of a post"""
        return self._post_act(obj)

    def _request_fb_places_id(self, obj: Location) -> str:
        if obj.lat is None or obj.lng is None:
            if obj.name is None:
                raise ValueError("Atleast a lat/lng combination or name needs to be specified.")
            resp = self._request("location_search", Method.GET, query={
                "search_query": obj.name,
                "rankToken": self._gen_uuid()
            })
        else:
            query = {
                "latitude": obj.lat,
                "longitude": obj.lng,
            }
            if obj.name:
                query['search_query'] = obj.name
            resp = self._request("location_search", Method.GET, query=query)

        as_json = resp.json()
        if as_json['status'] != 'ok':
            raise BadResponse

        return str(as_json['venues'][0]['external_id'])

    def _upload_image(self, path: str, waterfall_id: str, entity_length: str, entity_name: str, entity_type: str,
                      session_id: str, upload_id: str, quality: int) -> Response:
        headers = {
            'x-fb-photo-waterfall-id': waterfall_id,
            'x-entity-length': str(entity_length),
            'x-entity-name': entity_name,
            'x-instagram-rupload-params': json.dumps(build_default_rupload_params(upload_id, quality or 70)),
            'x-entity-type': entity_type,
            'offset': '0',
            'scene_capture_type': 'standard',
            'creation_logger_session_id': session_id
        }
        with open(path, 'rb') as f:
            return self._request(f'https://i.instagram.com/rupload_igphoto/{headers["x-entity-name"]}', Method.POST,
                          headers=headers, data=f.read())

    def post_post(self, obj: Union[PostStory, PostFeed], quality: int = None) -> Response:
        """Uploads a new picture/video to your Instagram account.
        Parameters
        ----------
        obj : Post
            Should be instantiated with all the required params
        quality : int
            Quality of the image, defaults to 70.
        Returns
        -------
        Response
            The response returned by the Instagram API.
        """
        as_dict = obj.fill(self).to_dict()
        if obj.device is None:
            d = Device(self.device_profile.manufacturer, self.device_profile.model,
                       int(self.device_profile.android_sdk_version), self.device_profile.android_release)
            obj.device = d

        self._upload_image(
            as_dict.pop('image_path'),
            as_dict.pop('x_fb_waterfall_id'),
            as_dict.pop("entity_length"),
            as_dict.pop("entity_name"),
            as_dict.pop("entity_type"),
            self.state.session_id,
            obj.upload_id,
            quality
        )

        if obj.location is not None:
            if not obj.location.facebook_places_id:
                obj.location.facebook_places_id = self._request_fb_places_id(obj.location)
            as_dict['location'] = json.dumps(obj.location.__dict__)

        headers = {
            'retry_context': json.dumps({"num_reupload": 0, "num_step_auto_retry": 0, "num_step_manual_retry": 0})
        }

        if obj.source_type == PostLocation.Feed.value:
            return self._request('media/configure/', Method.POST, data=as_dict, headers=headers, signed=True)
        elif obj.source_type == PostLocation.Story.value:
            return self._request('media/configure_to_story/', Method.POST, data=as_dict, headers=headers, signed=True)
        else:
            raise Exception("{} is not a supported post location.", obj.source_type)

    def post_retrieve_by_user(self, obj: RetrieveByUser) -> (RetrieveByUser, Union[dict, bool]):
        """Retrieves 12 posts of the user at a time. If there was a response / if there were any more posts
        available, the response can be found in original_requests/post.json:4

        Returns
        --------
        PostRetrieveByUser, (dict, bool)
            Will return the updated object and the response if there were any posts left, returns the object and
            False if not.
        """
        as_dict = obj.to_dict()

        if obj.page > 0 and obj.max_id is None:
            return obj, False

        as_dict.pop('max_id')
        as_dict.pop('user_id')

        resp = self._request(f'feed/user/{obj.user_id}/', Method.GET, query=as_dict)
        resp_as_json = resp.json()

        obj.max_id = resp_as_json.get('next_max_id')
        obj.page += 1
        return obj, resp_as_json['items']

    @staticmethod
    def _bytes_from_file(filename, chunksize):
        with open(filename, "rb") as f:
            while True:
                chunk = f.read(chunksize)
                if chunk:
                    yield chunk
                else:
                    break

    def _upload_video_in_chunks(self, obj: PostFeedVideo):
        rupload_params = json.dumps({
            "upload_media_height": str(int(obj.height)),
            "upload_media_width": str(int(obj.width)),
            "xsharing_user_ids": [],
            "upload_media_duration_ms": obj.length.replace('.', '').replace(',', ''),
            "upload_id": obj.upload_id,
            "retry_context": json.dumps({"num_step_auto_retry":0,"num_reupload":0,"num_step_manual_retry":0}),
            "media_type": "2"
        })
        resp = self._request(f"rupload_igvideo/{str(uuid.uuid4())}/", Method.POST, headers={
                                 "x-instagram-rupload-params": rupload_params,
                             }, query={"segmented": "true", "phase": "start"}, data="")
        headers = {
            'stream_id': resp.json()['stream_id'],
        }
        offset = 0
        for chunk in self._bytes_from_file(obj.path, 1024):
            entity_name = str(uuid.uuid4())
            resp = self._request(f"rupload_igvideo/{entity_name}?segmented=true&phase=transfer", Method.GET, headers=headers)
            self._request(f"rupload_igvideo/{entity_name}?segmented=true&phase=transfer", Method.POST, headers={
                **headers,
                **resp.json(),
                **{"segment-type": 3, 'x-entity-type': 'video/mp4', 'offset': '0', "segment-start-offset": str(offset)}
            }, data=chunk)

            offset += len(chunk)
        return headers

    def _upload_video_thumbnail(self, obj: PostFeedVideo, headers: dict):
        thumbnail_entity_name = str(uuid.uuid4())
        with open(obj.thumbnail_path, 'rb') as f:
            f.seek(0, 2)
            thumbnail_entity_length = f.tell()
        image_type = get_image_type(obj.thumbnail_path)
        if image_type not in ['jpg', 'jpeg']:
            raise ValueError("Instagram only accepts jpg/jpeg images")
        thumbnail_entity_type = f'image/{image_type}'
        waterfall_id = str(uuid.uuid4())

        self._request(f'rupload_igvideo/{thumbnail_entity_name}?segmented=true&phase=end', Method.POST, headers=headers)
        with open(obj.thumbnail_path, 'rb') as f:
            self._upload_image(obj.thumbnail_path, waterfall_id, str(thumbnail_entity_length), thumbnail_entity_name,
                               thumbnail_entity_type, self.state.session_id, str(time.time()), 0)

    def _finish_video_upload(self, obj: PostFeedVideo):
        as_dict = obj.fill(self).to_dict()
        as_dict = remove_from_dict(as_dict, ["path", "thumbnail_path", "creation_logger_session_id", "multi_sharing",
                                             "height", "width", "quality_info", "pdg_hash_info", ])
        self._request('media/upload_finish/?video=1', Method.POST, data=as_dict)

    def _configure_video(self, obj: PostFeedVideo):
        as_dict = obj.fill(self).to_dict()
        as_dict = remove_from_dict(as_dict, ["path", "thumbnail_path", "audio_muted", "height", "width",
                                             "quality_info", "pdg_hash_info"])
        self._request('media/upload_finish/?video=1', Method.POST, data=as_dict)

    def post_video(self, obj: PostFeedVideo):
        headers = self._upload_video_in_chunks(obj)
        self._upload_video_thumbnail(obj, headers)
        self._finish_video_upload(obj)
        self._configure_video(obj)
