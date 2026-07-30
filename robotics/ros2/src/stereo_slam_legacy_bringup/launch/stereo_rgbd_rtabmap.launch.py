import os
from launch import LaunchDescription
from launch_ros.actions import Node

def generate_launch_description():
    """启动双目转 RGB-D 后接入 RTAB-Map 的历史流程。"""
    # 统一一些参数（手持 + 15Hz + 低分辨率：approx_sync）
    sync_queue = 100
    approx_max = 0.05  # 手持建议 0.03~0.06 之间试

    # -------------------------------
    # -------------------------------
    tf_nodes = [
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='tf_cam_link_left',
            arguments=['0', '0', '0', '0', '0', '0', '1', 'camera_link', 'left_camera']
        ),
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='tf_cam_link_right',
            # baseline = 0.08192 
            arguments=['0', '-0.08192', '0', '0', '0', '0', '1', 'camera_link', 'right_camera']
        ),
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='tf_left_frame_optical',
            arguments=['0', '0', '0', '-1.5707963', '0', '-1.5707963', 'left_camera', 'left_camera_optical']
        ),
        Node(
            package='tf2_ros',
            executable='static_transform_publisher',
            name='tf_right_frame_optical',
            arguments=['0', '0', '0', '-1.5707963', '0', '-1.5707963', 'right_camera', 'right_camera_optical']
        ),
    ]

    # -------------------------------
    # 1) stereo_sync：把双目打包成 /rgbd_image
    #    输入：left/right image_rect + camera_info
    #    输出：/stereo_camera/rgbd_image  (rtabmap_msgs/RGBDImage)
    # -------------------------------
    stereo_sync = Node(
        package='rtabmap_sync',
        executable='stereo_sync',
        name='stereo_sync',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'approx_sync': True,                   # 手持更稳
            'approx_sync_max_interval': approx_max,
            'sync_queue_size': sync_queue,
        }],
        remappings=[
            # stereo_sync 默认订阅 left/image_rect、right/image_rect 等
            ('left/image_rect',   '/left_camera/image_rect'),
            ('right/image_rect',  '/right_camera/image_rect'),
            ('left/camera_info',  '/left_camera/camera_info'),
            ('right/camera_info', '/right_camera/camera_info'),

            # 默认发布 rgbd_image，这里直接 remap 到全局 /stereo_camera/rgbd_image
            ('rgbd_image',        '/stereo_camera/rgbd_image'),
        ]
    )

    # -------------------------------
    # 2) stereo_odometry：订阅 /stereo_camera/rgbd_image，输出 /vo
    # -------------------------------
    stereo_odometry = Node(
        package='rtabmap_odom',
        executable='stereo_odometry',
        name='stereo_odometry',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'frame_id': 'camera_link',
            'publish_tf': True,
            # 订阅 rgbd
            'subscribe_rgbd': True,
            'approx_sync': True,
            'approx_sync_max_interval': approx_max,
            'sync_queue_size': sync_queue,
            # 手持/低分辨率
            'Odom/MinInliers': '15',
            'Vis/MinInliers': '15',
            # 320 宽不建议 256，先 128 更稳
            'Stereo/MaxDisparity': '128',
            # 手持移动快：关键帧更勤一点
            'Odom/KeyFrameThr': '0.4',
        }],
        remappings=[
            ('rgbd_image', '/stereo_camera/rgbd_image'),
            ('odom', '/vo'),
        ]
    )

    # -------------------------------
    # 3) rtabmap：订阅 /stereo_camera/rgbd_image + /vo
    # -------------------------------
    rtabmap = Node(
        package='rtabmap_slam',
        executable='rtabmap',
        name='rtabmap',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'frame_id': 'camera_link',
            # 这里也订阅 rgbd
            'subscribe_rgbd': True,
            'approx_sync': True,
            'approx_sync_max_interval': approx_max,
            'sync_queue_size': sync_queue,
            'publish_tf': True,
            # 手持把最远距离压到 3m 左右
            'Grid/NormalsSegmentation': 'True',
            'Grid/MaxGroundHeight': '0.12',
            'Grid/MinGroundHeight': '-0.05',
            'Grid/MaxObstacleHeight': '2.0',
            'Grid/RangeMax': '3.0',
            'Grid/RayTracing': 'True',
            # 点云噪声过滤
            'Grid/NoiseFilteringRadius': '0.06',
            'Grid/NoiseFilteringMinNeighbors': '10',

            # 建图频率别太高
            'Rtabmap/DetectionRate': '2.0',
        }],
        remappings=[
            ('rgbd_image', '/stereo_camera/rgbd_image'),
            ('odom', '/vo'),
        ],
        arguments=['--delete_db_on_start']
    )

    # -------------------------------
    # 4) rtabmap_viz：订阅 /stereo_camera/rgbd_image + /vo
    # -------------------------------
    rtabmap_viz = Node(
        package='rtabmap_viz',
        executable='rtabmap_viz',
        name='rtabmap_viz',
        output='screen',
        parameters=[{
            'use_sim_time': False,
            'frame_id': 'camera_link',

            'subscribe_rgbd': True,

            'approx_sync': True,
            'approx_sync_max_interval': approx_max,
            'sync_queue_size': sync_queue,

            'publish_tf': False,
        }],
        remappings=[
            ('rgbd_image', '/stereo_camera/rgbd_image'),
            ('odom', '/vo'),
        ]
    )

    return LaunchDescription(
        tf_nodes + [
            stereo_sync,
            stereo_odometry,
            rtabmap,
            rtabmap_viz,
        ]
    )
