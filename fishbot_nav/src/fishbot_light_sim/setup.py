from glob import glob
import os

from setuptools import find_packages, setup

package_name = 'fishbot_light_sim'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            [os.path.join('resource', package_name)]),
        (os.path.join('share', package_name), ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'),
            glob('config/*.yaml') + glob('config/*.rviz')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='muqiao',
    maintainer_email='muqiao@localhost',
    description=(
        'FishBot 轻量 2D 仿真：栅格 raycast 雷达 + 差速里程计 + 虚拟障碍注入，'
        '复用真实地图与 Nav2 参数做导航避障算法迭代'),
    license='MIT',
    entry_points={
        'console_scripts': [
            'fishbot_light_sim = fishbot_light_sim.light_sim_node:main',
        ],
    },
)
