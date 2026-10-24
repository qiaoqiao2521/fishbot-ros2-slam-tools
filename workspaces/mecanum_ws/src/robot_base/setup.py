from setuptools import find_packages, setup
import os
from glob import glob

package_name = 'robot_base'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml', 'LICENSE', 'UPSTREAM.md']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'config', 'behavior_trees'), glob('config/behavior_trees/*.xml')),
        (os.path.join('share', package_name, 'rviz'), glob('rviz/*.rviz')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='qiaoqiao2521',
    maintainer_email='qiaoqiao2521@users.noreply.github.com',
    description='Robot base package for mecanum drive',
    license='Apache License 2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'drive_node = robot_base.drive_node:main',
            'map_republisher = robot_base.map_republisher:main',
        ],
    },
)
