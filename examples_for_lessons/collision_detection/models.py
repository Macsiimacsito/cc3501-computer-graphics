import pyglet
from pyglet.window import key

from OpenGL.GL import *

import numpy as np
import sys, os.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from collections import deque  # to allow use of double linked lists
# We will need double linked lists because we are going to remove elements at the beginning
# But also add many at the end

import grafica.basic_shapes as bs
import grafica.easy_shaders as es
import grafica.transformations as tr
from grafica.assets_path import getAssetPath


GROUND_Y_LEVEL = -0.8
INITIAL_JUMP_SPEED_IN_Y = 0.3
GRAVITY = 0.2

class GameState:
    """Class to keep track of the current game State. Such as the current player, the models,
    total time played, etc.
    """
    camera_position = 0.0
    total_time_played = 0.0
    player: 'Player' = None
    obstacle_manager: 'ObstacleManager' = None

    def update(self, dt: float):
        self.camera_position = self.player.x
        self.total_time_played += dt


class ObstacleManager:
    """Class to make sure that obstacles are not on top of each other
    and that the player can always pass through."""

    obstacles: deque = deque()
    X_DISTANCE_BETWEEN_OBSTACLES_STD = 0.3
    FIRST_OBSTACLE_OFFSET_IN_X = 0.8


    @classmethod
    def __new__(cls):
        """ This function makes sure we always get the same instance of ObstacleManager.
        Even when trying to create a new one. This is useful since we do not need to keep
        the reference
        """
        if not hasattr(cls, 'instance'):
            cls.instance = super(ObstacleManager, cls).__new__(cls)
        return cls.instance

    @classmethod
    def add_new_obstacle(cls, obstacle: 'Obstacle'):
        cls.obstacles.append(obstacle)
        cls._set_random_position(obstacle)

    @classmethod
    def _set_random_position(cls, curr_obstacle: 'Obstacle'):
        """
        Supposing each obstacle is added from left to right. Then try to add this 
        obstacle at a random position at the right of the obstacle to the right
        if we keed this idea, we only need to check the last elements each time we add
        a new obstacle- Since these methods will be called during runtime, these
        functions need to be efficient.
        """
        if len(cls.obstacles <= 0):
            cls._simple_set_obstacle_at_the_right_of_player()

        else:
            last_positioned_obstacle = cls.obstacles[-1]
            # Suggest a random position for our obstacle plus an offset
            # We will consider a standard deviation of 0.3 to make sure all
            # obstacles are near each other
            std_sigma = cls.X_DISTANCE_BETWEEN_OBSTACLES_STD
            curr_obstacle.x = last_positioned_obstacle.x + abs(np.random.randn(1) * std_sigma)
            
            # We need to make sure that this element does not overlap with the last one
            # So we reallocate it recursively until they do not overlap anymore
            while cls._obstacles_do_overlap(curr_obstacle, last_positioned_obstacle):
                std_sigma = std_sigma * 0.5
                curr_obstacle.x = last_positioned_obstacle.x + abs(np.random.randn(1) * std_sigma)


    @classmethod
    def _simple_set_obstacle_at_the_right_of_player(cls, curr_obstacle: 'Obstacle'):
        # just add it to the right of the player before the player can see it
        gameState = GameState()
        player_position_x = gameState.player.x
        curr_obstacle.x = player_position_x + cls.FIRST_OBSTACLE_OFFSET_IN_X
        cls.obstacles.append(curr_obstacle)

    @classmethod
    def _obstacles_do_overlap(cls, obs1, obs2):
        x_overlap = False
        y_overlap = False

        obs1_at_the_left = obs1.x <= obs2.x
        if obs1_at_the_left:
            x_overlap = obs1.higher_x_bound >= obs2.lower_x_bound
        else:
            x_overlap = obs1.higher_x_bound <= obs2.lower_x_bound
        
        obs1_on_top = obs1.y >= obs2.y
        if obs1_on_top:
            y_overlap = obs1.lower_y_bound >= obs2.higher_y_bound
        else:
            y_overlap = obs1.lower_y_bound <= obs2.higher_y_bound

        return x_overlap and y_overlap


class CollisionObject:

    def __init__(self, x, y, lower_x_bound, higher_x_bound, lower_y_bound, higher_y_bound):
        self.x = x
        self.y = y
        self.lower_x_bound = lower_x_bound
        self.higher_x_bound = higher_x_bound
        self.lower_y_bound = lower_y_bound
        self.higher_y_bound = higher_y_bound

    def is_colliding_with_object(self, other: 'CollisionObject') -> bool:
        # This implementation does not consider width or height of the current object
        # Check that self.x is in the range []
        collides_in_x = other.lower_x_bound <= self.x - other.x <= other.higher_x_bound
        collides_in_y = other.lower_y_bound <= self.y - other.y <= other.higher_y_bound
        if collides_in_x and collides_in_y:
            return True
        return False


class Player(CollisionObject):

    def __init__(self, x, y=GROUND_Y_LEVEL):
        lower_x_bound = 0.1
        higher_x_bound = 0.1
        lower_y_bound = 0.1
        higher_y_bound = 0.1
        speed = [0.1, 0.0]
        super().__init__(x, y, lower_x_bound, higher_x_bound, lower_y_bound, higher_y_bound)
        self.speed = speed
        self._is_in_air = False

    def update(self, dt, controller):
        # Assuming linear speed
        self.x += self.speed[0] * dt
        self.y += self.speed[1] * dt
        if controller.jump_action_queued and not self._is_in_air:
            # Start jumping
            self.speed[1] = INITIAL_JUMP_SPEED_IN_Y
            self._is_in_air = True
            controller.jump_action_queued = False

        if self._is_in_air:
            self.speed[1] = self.speed[1] - GRAVITY * dt 
            self._is_in_air = True if self.y >= GROUND_Y_LEVEL else False
        else:
            self.speed[1] = 0.0

        # Always fall, until the ground is found
        self.y = max(self.y + self.speed[1] * dt, GROUND_Y_LEVEL)
        

    def set_gpu_shape(self, pipeline):
        shape_player = bs.createTextureQuad(1,1)
        self.gpu_player = es.GPUShape().initBuffers()
        pipeline.setupVAO(self.gpu_player)
        self.gpu_player.fillBuffers(shape_player.vertices, shape_player.indices, GL_STATIC_DRAW)
        self.gpu_player.texture = es.textureSimpleSetup(
            getAssetPath("boo.png"), GL_CLAMP_TO_EDGE, GL_CLAMP_TO_EDGE, GL_NEAREST, GL_NEAREST)


DESTRUCT_OFFSET_IN_X = 1.0

class Obstacle(CollisionObject):

    def __init__(self, x, y, lower_x_bound, higher_x_bound, lower_y_bound, higher_y_bound):
        super().__init__(x, y, lower_x_bound, higher_x_bound, lower_y_bound, higher_y_bound)
        ObstacleManager.obstacles.append(self)
        ObstacleManager.set_random_position(self)

    def render(self):
        pass


    def check_for_destroy(self):
        """ Checks whether this object should be destroyed to save memory"""
        if self.x <= GameState.camera_position - DESTRUCT_OFFSET_IN_X:
            del self