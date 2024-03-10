"""Rail generators (infrastructure manager, "Infrastrukturbetreiber")."""
import copy
import sys
import warnings
from typing import Callable, Tuple, Optional, Dict, List

import numpy as np
from numpy.random.mtrand import RandomState

from flatland.core.grid.grid4 import Grid4TransitionsEnum
from flatland.core.grid.grid4_utils import get_direction, mirror, direction_to_point
from flatland.core.grid.grid_utils import Vec2dOperations as Vec2d
from flatland.core.grid.grid_utils import distance_on_rail, IntVector2DArray, IntVector2D, \
    Vec2dOperations
from flatland.core.grid.rail_env_grid import RailEnvTransitions
from flatland.core.transition_map import GridTransitionMap
from flatland.envs.grid4_generators_utils import connect_rail_in_grid_map, connect_straight_line_in_grid_map, \
    fix_inner_nodes, align_cell_to_city
from flatland.envs import persistence
from flatland1.utils.simple_rail import make_custom_rail
from flatland1.utils.simple_rail import make_double_track


RailGeneratorProduct = Tuple[GridTransitionMap, Optional[Dict]]
""" A rail generator returns a RailGenerator Product, which is just
    a GridTransitionMap followed by an (optional) dict/
"""

RailGenerator = Callable[[int, int, int, int], RailGeneratorProduct]


class RailGen(object):
    """ Base class for RailGen(erator) replacement

        WIP to replace bare generators with classes / objects without unnamed local variables
        which prevent pickling.
    """
    def __init__(self, *args, **kwargs):
        """ constructor to record any state to be reused in each "generation"
        """
        pass

    def generate(self, width: int, height: int, num_agents: int, num_resets: int = 0,
                  np_random: RandomState = None) -> RailGeneratorProduct:
        pass

    def __call__(self, *args, **kwargs) -> RailGeneratorProduct:
        return self.generate(*args, **kwargs)






def sparse1_rail_generator(*args, **kwargs):
    return SparseRailGen(*args, **kwargs)

class SparseRailGen(RailGen):

    def __init__(self, max_num_cities: int = 2, grid_mode: bool = False, max_rails_between_cities: int = 2,
                          max_rail_pairs_in_city: int = 2, seed=None) -> RailGenerator:
        """
        Generates railway networks with cities and inner city rails

        Parameters
        ----------
        max_num_cities : int
            Max number of cities to build. The generator tries to achieve this numbers given all the parameters
        grid_mode: Bool
            How to distribute the cities in the path, either equally in a grid or random
        max_rails_between_cities: int
            Max number of rails connecting to a city. This is only the number of connection points at city boarder.
            Number of tracks drawn inbetween cities can still vary
        max_rail_pairs_in_city: int
            Number of parallel tracks in the city. This represents the number of tracks in the trainstations
        seed: int
            Initiate the seed

        Returns
        -------
        Returns the rail generator object to the rail env constructor
        """
        self.max_num_cities = max_num_cities
        self.grid_mode = grid_mode
        self.max_rails_between_cities = max_rails_between_cities
        self.max_rail_pairs_in_city = max_rail_pairs_in_city
        self.seed = seed


    def generate(self, width: int, height: int, num_agents: int, num_resets: int = 0,
                  np_random: RandomState = None) -> RailGenerator:
        """

        Parameters
        ----------
        width: int
            Width of the environment
        height: int
            Height of the environment
        num_agents:
            Number of agents to be placed within the environment
        num_resets: int
            Count for how often the environment has been reset

        Returns
        -------
        Returns the grid_map --> The railway infrastructure
        Hints:
        agents_hints': {
            'num_agents': how many agents have starting and end spots
            'agent_start_targets_cities': touples of agent start and target cities
            'train_stations': locations of train stations for start and targets
            'city_orientations' : orientation of cities
        """
        if self.seed is not None:
            np_random = RandomState(self.seed)
        elif np_random is None:
            np_random = RandomState(np.random.randint(2**32))

        rail_trans = RailEnvTransitions()
        grid_map = GridTransitionMap(width=width, height=height, transitions=rail_trans)

        # NEW : SCHED CONST (Pairs of rails (1,2,3 pairs))
        min_nr_rail_pairs_in_city = 1 # (min pair must be 1)
        rail_pairs_in_city = min_nr_rail_pairs_in_city if self.max_rail_pairs_in_city < min_nr_rail_pairs_in_city else self.max_rail_pairs_in_city # (pairs can be 1,2,3)
        rails_between_cities = (rail_pairs_in_city*2) if self.max_rails_between_cities > (rail_pairs_in_city*2) else self.max_rails_between_cities

        # We compute the city radius by the given max number of rails it can contain.
        # The radius is equal to the number of tracks divided by 2
        # We add 2 cells to avoid that track lenght is to short
        city_padding = 2
        # We use ceil if we get uneven numbers of city radius. This is to guarantee that all rails fit within the city.
        city_radius = int(np.ceil((rail_pairs_in_city*2) / 2)) + city_padding
        vector_field = np.zeros(shape=(height, width)) - 1.

        # Calculate the max number of cities allowed
        # and reduce the number of cities to build to avoid problems
        max_feasible_cities = min(self.max_num_cities,
                                  ((height - 2) // (2 * (city_radius + 1))) * ((width - 2) // (2 * (city_radius + 1))))

        if max_feasible_cities < 2:
            # sys.exit("[ABORT] Cannot fit more than one city in this map, no feasible environment possible! Aborting.")
            raise ValueError("ERROR: Cannot fit more than one city in this map, no feasible environment possible!")

        # Evenly distribute cities
        if self.grid_mode:
            city_positions = self._generate_evenly_distr_city_positions(max_feasible_cities, city_radius, width,
                                                                   height)
        # Distribute cities randomly
        else:
            city_positions = self._generate_random_city_positions(max_feasible_cities, city_radius, width, height,
                                                             np_random=np_random)
            # for large environments check that the cities are not grouped in separate cliques, otherwise find new
            # positions for cities
            if self.max_num_cities > 4:
                contains_cliques = self.contains_cliques(city_positions)
                while contains_cliques:
                    city_positions = self._generate_random_city_positions(max_feasible_cities, city_radius, width, height,
                                                                      np_random=np_random)
                    contains_cliques = self.contains_cliques(city_positions)
        # reduce num_cities if less were generated in random mode
        num_cities = len(city_positions)
        # If random generation failed just put the cities evenly
        if num_cities < 2:
            warnings.warn("[WARNING] Changing to Grid mode to place at least 2 cities.")
            city_positions = self._generate_evenly_distr_city_positions(max_feasible_cities, city_radius, width,
                                                                   height)
        num_cities = len(city_positions)
        # Set up connection points for all cities
        inner_connection_points, outer_connection_points, city_orientations, city_cells = \
            self._generate_city_connection_points(
                city_positions, city_radius, vector_field, rails_between_cities,
                rail_pairs_in_city, np_random=np_random)

        # Connect the cities through the connection points
        inter_city_lines = self._connect_cities(city_positions, outer_connection_points, city_cells,
                                           rail_trans, grid_map)

        # Build inner cities
        free_rails = self._build_inner_cities(city_positions, inner_connection_points,
                                         outer_connection_points,
                                         rail_trans,
                                         grid_map)

        # Populate cities
        train_stations = self._set_trainstation_positions(city_positions, city_radius, free_rails)

        # Fix all transition elements
        self._fix_transitions(city_cells, inter_city_lines, grid_map, vector_field)
        return grid_map, {'agents_hints': {
            'city_positions': city_positions,
            'train_stations': train_stations,
            'city_orientations': city_orientations
        }}

    def build_clique3(self, index_array, index):
        closest_index1 = index_array[index][0]
        closest_index2 = index_array[index][1]
        closest_index3 = index_array[index][2]
        clique3 = sorted([closest_index1, closest_index2, closest_index3])
        return clique3

    def contains_cliques(self, city_positions):
        """
        If we want to include the possibility of having dead end cities with only one entry/exit side, we need to
        exclude the possibility that cities are clustered into cliques of size 3 or 4 (at least for max_num_cities = 8).
        To check for cliques of size 3 we check the closest two neighbours for every city, since they are all connected
        in a 3-clique. For cliques of size 4 we also only check the two closest neighbours, because there is no direct
        connection to the fourth city, but include four cities in our search.
        """
        distance_array = np.empty((len(city_positions), len(city_positions)), dtype=int)
        sort_index = np.empty((len(city_positions), len(city_positions)), dtype=int)
        for i in range(len(city_positions)):
            for j in range(len(city_positions)):
                distance_array[i][j] = Vec2d.get_manhattan_distance(city_positions[i], city_positions[j])
        for i in range(len(city_positions)):
            sort_index[i] = np.argsort(distance_array[i])
        for i in range(len(city_positions)):
            clique3 = self.build_clique3(sort_index, i)
            clique31 = self.build_clique3(sort_index, clique3[1])
            clique32 = self.build_clique3(sort_index, clique3[2])
            if clique3 == clique31 and clique3 == clique32:
                return True
            else:
                cluster = list(dict.fromkeys(clique3 + clique31 + clique32))
                if len(cluster) == 4:
                    additional_element = list(set(cluster) - set(clique3))[0]
                    clique33 = self.build_clique3(sort_index, additional_element)
                    if cluster == list(dict.fromkeys(cluster + clique33)):
                        return True
        return False

    def _generate_random_city_positions(self, num_cities: int, city_radius: int, width: int,
                                        height: int, np_random: RandomState = None) -> Tuple[
        IntVector2DArray, IntVector2DArray]:
        """
        Distribute the cities randomly in the environment while respecting city sizes and guaranteeing that they
        don't overlap.

        Parameters
        ----------
        num_cities: int
            Max number of cities that should be placed
        city_radius: int
            Radius of each city. Cities are squares with edge length 2 * city_radius + 1
        width: int
            Width of the environment
        height: int
            Height of the environment

        Returns
        -------
        Returns a list of all city positions as coordinates (x,y)

        """

        city_positions: IntVector2DArray = []

        # We track a grid of allowed indexes that can be sampled from for creating a new city
        # This removes the old sampling method of retrying a random sample on failure
        allowed_grid = np.zeros((height, width), dtype=np.uint8)
        city_radius_pad1 = city_radius + 1
        # Borders have to be not allowed from the start
        # allowed_grid == 1 indicates locations that are allowed
        allowed_grid[city_radius_pad1:-city_radius_pad1, city_radius_pad1:-city_radius_pad1] = 1
        for _ in range(num_cities):
            allowed_indexes = np.where(allowed_grid == 1)
            num_allowed_points = len(allowed_indexes[0])
            if num_allowed_points == 0:
                break
            # Sample one of the allowed indexes
            point_index = np_random.randint(num_allowed_points)
            row = int(allowed_indexes[0][point_index])
            col = int(allowed_indexes[1][point_index])

            # Need to block city radius and extra margin so that next sampling is correct
            # Clipping handles the case for negative indexes being generated
            row_start = max(0, row - 2 * city_radius_pad1)
            col_start = max(0, col - 2 * city_radius_pad1)
            row_end = row + 2 * city_radius_pad1 + 1
            col_end = col + 2 * city_radius_pad1 + 1

            allowed_grid[row_start : row_end, col_start : col_end] = 0

            city_positions.append((row, col))

        created_cites = len(city_positions)
        if created_cites < num_cities:
            city_warning = f"Could not set all required cities! Created {created_cites}/{num_cities}"
            warnings.warn(city_warning)
        return city_positions

    def _generate_evenly_distr_city_positions(self, num_cities: int, city_radius: int, width: int, height: int
                                              ) -> Tuple[IntVector2DArray, IntVector2DArray]:
        """
        Distribute the cities in an evenly spaced grid

        Parameters
        ----------
        num_cities: int
            Max number of cities that should be placed
        city_radius: int
            Radius of each city. Cities are squares with edge length 2 * city_radius + 1
        width: int
            Width of the environment
        height: int
            Height of the environment

        Returns
        -------
        Returns a list of all city positions as coordinates (x,y)

        """
        aspect_ratio = height / width
        # Compute max numbe of possible cities per row and col.
        # Respect padding at edges of environment
        # Respect padding between cities
        padding = 2
        city_size = 2 * (city_radius + 1)
        max_cities_per_row = int((height - padding) // city_size)
        max_cities_per_col = int((width - padding) // city_size)

        # Choose number of cities per row.
        # Limit if it is more then max number of possible cities

        cities_per_row = min(int(np.ceil(np.sqrt(num_cities * aspect_ratio))), max_cities_per_row)
        cities_per_col = min(int(np.ceil(num_cities / cities_per_row)), max_cities_per_col)
        num_build_cities = min(num_cities, cities_per_col * cities_per_row)
        row_positions = np.linspace(city_radius + 2, height - (city_radius + 2), cities_per_row, dtype=int)
        col_positions = np.linspace(city_radius + 2, width - (city_radius + 2), cities_per_col, dtype=int)
        city_positions = []

        for city_idx in range(num_build_cities):
            row = row_positions[city_idx % cities_per_row]
            col = col_positions[city_idx // cities_per_row]
            city_positions.append((row, col))
        return city_positions

    def _generate_city_connection_points(self, city_positions: IntVector2DArray, city_radius: int,
                                         vector_field: IntVector2DArray, rails_between_cities: int,
                                         rail_pairs_in_city: int = 1, np_random: RandomState = None) -> Tuple[
        List[List[List[IntVector2D]]],
        List[List[List[IntVector2D]]],
        List[np.ndarray],
        List[Grid4TransitionsEnum]]:
        """
        Generate the city connection points. Internal connection points are used to generate the parallel paths
        within the city.
        External connection points are used to connect different cities together

        Parameters
        ----------
        city_positions: IntVector2DArray
            Vector that contains all the positions of the cities
        city_radius: int
            Radius of each city. Cities are squares with edge length 2 * city_radius + 1
        vector_field: IntVector2DArray
            Vectorfield of the size of the environment. It is used to generate preferred orienations for each cell.
            Each cell contains the prefered orientation of cells. If no prefered orientation is present it is set to -1
        rails_between_cities: int
            Number of rails that connect out from the city
        rail_pairs_in_city: int
            Number of rails within the city

        Returns
        -------
        inner_connection_points: List of List of length number of cities
            Contains all the inner connection points for each boarder of each city.
            [North_Points, East_Poinst, South_Points, West_Points]
        outer_connection_points: List of List of length number of cities
            Contains all the outer connection points for each boarder of the city.
            [North_Points, East_Poinst, South_Points, West_Points]
        city_orientations: List of length number of cities
            Contains all the orientations of cities. This is then used to orient agents according to the rails
        city_cells: List
            List containing the coordinates of all the cells that belong to a city. This is used by other algorithms
            to avoid drawing inter-city-rails through cities.
        """
        inner_connection_points: List[List[List[IntVector2D]]] = []
        outer_connection_points: List[List[List[IntVector2D]]] = []
        city_orientations: List[Grid4TransitionsEnum] = []
        city_cells: IntVector2DArray = []

        for city_position in city_positions:

            # Chose the directions where close cities are situated
            neighb_dist = []
            for neighbour_city in city_positions:
                neighb_dist.append(Vec2dOperations.get_manhattan_distance(city_position, neighbour_city))
            closest_neighb_idx = self.__class__.argsort(neighb_dist)

            # Store the directions to these neighbours and orient city to face closest neighbour
            connection_sides_idx = []
            idx = 1
            if self.grid_mode:
                current_closest_direction = np_random.randint(4)
            else:
                current_closest_direction = direction_to_point(city_position, city_positions[closest_neighb_idx[idx]])
            connection_sides_idx.append(current_closest_direction)
            connection_sides_idx.append((current_closest_direction + 2) % 4)
            city_orientations.append(current_closest_direction)
            city_cells.extend(self._get_cells_in_city(city_position, city_radius, city_orientations[-1], vector_field))
            # set the number of tracks within a city, at least 2 tracks per city
            connections_per_direction = np.zeros(4, dtype=int)
            # NEW : SCHED CONST
            # nr_of_connection_points = np_random.randint(1, rail_pairs_in_city + 1) * 2  # can be (1,2,3)*2 = (2,4,6)
            # we fix the number of connection points since we always want two tracks in between cities
            nr_of_connection_points = np_random.randint(1, rail_pairs_in_city + 1) * 2
            for idx in connection_sides_idx:
                connections_per_direction[idx] = nr_of_connection_points
            connection_points_coordinates_inner: List[List[IntVector2D]] = [[] for i in range(4)]
            connection_points_coordinates_outer: List[List[IntVector2D]] = [[] for i in range(4)]
            # number_of_out_rails = np_random.randint(1, min(rails_between_cities, nr_of_connection_points) + 1)
            # similarly we also fix the number of outgoing tracks to 2
            number_of_out_rails = 2
            start_idx = int((nr_of_connection_points - number_of_out_rails) / 2)
            for direction in range(4):
                connection_slots = np.arange(nr_of_connection_points) - start_idx
                # Offset the rails away from the center of the city
                offset_distances = np.arange(nr_of_connection_points) - int(nr_of_connection_points / 2)
                # The clipping helps offsetting one side more than the other to avoid switches at same locations
                # The magic number plus one is added such that all points have at least one offset
                inner_point_offset = np.abs(offset_distances) + np.clip(offset_distances, 0, 1) + 1
                for connection_idx in range(connections_per_direction[direction]):
                    if direction == 0:
                        tmp_coordinates = (
                            city_position[0] - city_radius + inner_point_offset[connection_idx],
                            city_position[1] + connection_slots[connection_idx])
                        out_tmp_coordinates = (
                            city_position[0] - city_radius, city_position[1] + connection_slots[connection_idx])
                    if direction == 1:
                        tmp_coordinates = (
                            city_position[0] + connection_slots[connection_idx],
                            city_position[1] + city_radius - inner_point_offset[connection_idx])
                        out_tmp_coordinates = (
                            city_position[0] + connection_slots[connection_idx], city_position[1] + city_radius)
                    if direction == 2:
                        tmp_coordinates = (
                            city_position[0] + city_radius - inner_point_offset[connection_idx],
                            city_position[1] + connection_slots[connection_idx])
                        out_tmp_coordinates = (
                            city_position[0] + city_radius, city_position[1] + connection_slots[connection_idx])
                    if direction == 3:
                        tmp_coordinates = (
                            city_position[0] + connection_slots[connection_idx],
                            city_position[1] - city_radius + inner_point_offset[connection_idx])
                        out_tmp_coordinates = (
                            city_position[0] + connection_slots[connection_idx], city_position[1] - city_radius)
                    connection_points_coordinates_inner[direction].append(tmp_coordinates)
                    if connection_idx in range(start_idx, start_idx + number_of_out_rails):
                        connection_points_coordinates_outer[direction].append(out_tmp_coordinates)

            inner_connection_points.append(connection_points_coordinates_inner)
            outer_connection_points.append(connection_points_coordinates_outer)
        return inner_connection_points, outer_connection_points, city_orientations, city_cells

    def _connect_cities(self, city_positions: IntVector2DArray, connection_points: List[List[List[IntVector2D]]],
                        city_cells: IntVector2DArray,
                        rail_trans: RailEnvTransitions, grid_map: RailEnvTransitions) -> List[IntVector2DArray]:
        """
        Connects cities together through rails. Each city connects from its outgoing connection points to the closest
        cities. This guarantees that all connection points are used.

        Parameters
        ----------
        city_positions: IntVector2DArray
            All coordinates of the cities
        connection_points: List[List[List[IntVector2D]]]
            List of coordinates of all outer connection points
        city_cells: IntVector2DArray
            Coordinates of all the cells contained in any city. This is used to avoid drawing rails through existing
            cities.
        rail_trans: RailEnvTransitions
            Railway transition objects
        grid_map: RailEnvTransitions
            The grid map containing the rails. Used to draw new rails

        Returns
        -------
        Returns a list of all the cells (Coordinates) that belong to a rail path. This can be used to access railway
        cells later.
        """
        all_paths: List[IntVector2DArray] = []

        grid4_directions = [Grid4TransitionsEnum.NORTH, Grid4TransitionsEnum.EAST, Grid4TransitionsEnum.SOUTH,
                            Grid4TransitionsEnum.WEST]
        set_of_connections = []
        for current_city_idx in np.arange(len(city_positions)):
            closest_neighbours = self._closest_neighbour_in_grid4_directions(current_city_idx, city_positions)
            city_position = city_positions[current_city_idx]
            neighb_dist = []
            for neighbour_city in city_positions:
                neighb_dist.append(Vec2dOperations.get_manhattan_distance(city_position, neighbour_city))
            closest_neighb_idx = self.__class__.argsort(neighb_dist)
            closest_direction = direction_to_point(city_position, city_positions[closest_neighb_idx[1]])
            if not connection_points[current_city_idx][closest_direction]:
                closest_direction = (closest_direction + 1) % 4
                second_closest_direction = (closest_direction + 2) % 4
            else:
                second_closest_direction = direction_to_point(city_position, city_positions[closest_neighb_idx[2]])
                if not connection_points[current_city_idx][second_closest_direction]:
                    second_closest_direction = (closest_direction + 2) % 4
            out_direction = closest_direction
            connection_points_copy = copy.deepcopy(connection_points)
            i = 0
            for city_out_connection_point in connection_points[current_city_idx][out_direction]:
                if i % 2 == 0:
                    min_connection_dist = np.inf
                    for direction in grid4_directions:
                        current_points = connection_points_copy[closest_neighb_idx[1]][direction]
                        for tmp_in_connection_point in current_points:
                            tmp_dist = Vec2dOperations.get_manhattan_distance(city_out_connection_point,
                                                                              tmp_in_connection_point)
                            if tmp_dist < min_connection_dist:
                                min_connection_dist = tmp_dist
                                neighbour_connection_point = tmp_in_connection_point
                                city_out_connection_point = city_out_connection_point
                                current_direction = direction
                                neighbour_index_for_connection = closest_neighb_idx[1]
                    # choose always the first connection point of a neighbour, because the list is ordered, same as the
                    # list of the outer connection point
                    possible_connection = [current_city_idx, neighbour_index_for_connection]
                    reversed_possible_connection = [neighbour_index_for_connection, current_city_idx]
                    city_direction = direction_to_point(city_position, city_out_connection_point)
                    neighbour_direction = direction_to_point(city_positions[closest_neighb_idx[1]], neighbour_connection_point)
                    if reversed_possible_connection not in set_of_connections:
                        if city_direction + neighbour_direction in [1, 5] or city_direction == neighbour_direction:
                            neighbour_connection_point = connection_points_copy[closest_neighb_idx[1]][current_direction][1]
                            next_neighbour_connection_point = connection_points_copy[closest_neighb_idx[1]][current_direction][0]
                        else:
                            neighbour_connection_point = connection_points_copy[closest_neighb_idx[1]][current_direction][0]
                            next_neighbour_connection_point = \
                                connection_points_copy[closest_neighb_idx[1]][current_direction][1]
                        connection_points_copy[closest_neighb_idx[1]][current_direction].remove(neighbour_connection_point)
                        last_city_out_connection_point = city_out_connection_point

                    else:
                        i += 1
                else:
                    if (city_direction == 0 or city_direction == 1)  and \
                        ((neighbour_connection_point[0] < last_city_out_connection_point[0] and \
                        neighbour_connection_point[1] > last_city_out_connection_point[1]) or \
                        (neighbour_connection_point[0] > last_city_out_connection_point[0] and \
                        neighbour_connection_point[1] < last_city_out_connection_point[1])) or \
                        (city_direction == 2 or city_direction == 3) and \
                        ((neighbour_connection_point[0] < last_city_out_connection_point[0] and \
                          neighbour_connection_point[1] < last_city_out_connection_point[1]) or \
                         (neighbour_connection_point[0] > last_city_out_connection_point[0] and \
                          neighbour_connection_point[1] > last_city_out_connection_point[1])):

                        new_line = connect_rail_in_grid_map(grid_map, city_out_connection_point,
                                                            next_neighbour_connection_point,
                                                            rail_trans, flip_start_node_trans=False,
                                                            flip_end_node_trans=False,
                                                            respect_transition_validity=False,
                                                            avoid_rail=True,
                                                            forbidden_cells=city_cells)
                        if len(new_line) == 0:
                            warnings.warn("[WARNING] No line added between stations")
                        elif new_line[-1] != next_neighbour_connection_point or new_line[
                            0] != city_out_connection_point:
                            warnings.warn("[WARNING] Unable to connect requested stations")
                        all_paths.extend(new_line)

                        new_line = connect_rail_in_grid_map(grid_map, last_city_out_connection_point,
                                                            neighbour_connection_point,
                                                            rail_trans, flip_start_node_trans=False,
                                                            flip_end_node_trans=False,
                                                            respect_transition_validity=False,
                                                            avoid_rail=True,
                                                            forbidden_cells=city_cells)
                        if len(new_line) == 0:
                            warnings.warn("[WARNING] No line added between stations")
                        elif new_line[-1] != neighbour_connection_point or new_line[
                            0] != last_city_out_connection_point:
                            warnings.warn("[WARNING] Unable to connect requested stations")
                        all_paths.extend(new_line)
                        set_of_connections.append(possible_connection)
                    else:

                        new_line = connect_rail_in_grid_map(grid_map, last_city_out_connection_point, neighbour_connection_point,
                                                            rail_trans, flip_start_node_trans=False,
                                                            flip_end_node_trans=False, respect_transition_validity=False,
                                                            avoid_rail=True,
                                                            forbidden_cells=city_cells)
                        if len(new_line) == 0:
                            warnings.warn("[WARNING] No line added between stations")
                        elif new_line[-1] != neighbour_connection_point or new_line[0] != last_city_out_connection_point:
                            warnings.warn("[WARNING] Unable to connect requested stations")
                        all_paths.extend(new_line)
                        set_of_connections.append(possible_connection)

                        new_line = connect_rail_in_grid_map(grid_map, city_out_connection_point, next_neighbour_connection_point,
                                                            rail_trans, flip_start_node_trans=False,
                                                            flip_end_node_trans=False, respect_transition_validity=False,
                                                            avoid_rail=True,
                                                            forbidden_cells=city_cells)
                        if len(new_line) == 0:
                            warnings.warn("[WARNING] No line added between stations")
                        elif new_line[-1] != next_neighbour_connection_point or new_line[0] != city_out_connection_point:
                            warnings.warn("[WARNING] Unable to connect requested stations")
                        all_paths.extend(new_line)
                i += 1
            if closest_direction != second_closest_direction:
                out_direction = second_closest_direction
                connection_points_copy = copy.deepcopy(connection_points)
                for city_out_connection_point in connection_points[current_city_idx][out_direction]:
                    if i % 2 == 0:
                        min_connection_dist = np.inf
                        for direction in grid4_directions:
                            current_points = connection_points_copy[closest_neighb_idx[2]][direction]
                            for tmp_in_connection_point in current_points:
                                tmp_dist = Vec2dOperations.get_manhattan_distance(city_out_connection_point,
                                                                                      tmp_in_connection_point)
                                if tmp_dist < min_connection_dist:
                                    min_connection_dist = tmp_dist
                                    neighbour_connection_point = tmp_in_connection_point
                                    city_out_connection_point = city_out_connection_point
                                    current_direction = direction
                                    neighbour_index_for_connection = closest_neighb_idx[2]

                        possible_connection = [current_city_idx, neighbour_index_for_connection]
                        reversed_possible_connection = [neighbour_index_for_connection, current_city_idx]
                        city_direction = direction_to_point(city_position, city_out_connection_point)
                        neighbour_direction = direction_to_point(city_positions[closest_neighb_idx[2]], neighbour_connection_point)
                        if reversed_possible_connection not in set_of_connections:
                            if city_direction + neighbour_direction in [1, 5] or city_direction == neighbour_direction:
                                neighbour_connection_point = \
                                    connection_points_copy[closest_neighb_idx[2]][current_direction][1]
                                next_neighbour_connection_point = \
                                    connection_points_copy[closest_neighb_idx[2]][current_direction][0]
                            else:
                                neighbour_connection_point = connection_points_copy[closest_neighb_idx[2]][current_direction][0]
                                next_neighbour_connection_point = \
                                connection_points_copy[closest_neighb_idx[2]][current_direction][1]
                            connection_points_copy[closest_neighb_idx[2]][current_direction].remove(neighbour_connection_point)
                            last_city_out_connection_point = city_out_connection_point

                        else:
                            i += 1
                    else:
                        if (city_direction == 0 or city_direction == 1)  and \
                        ((neighbour_connection_point[0] < last_city_out_connection_point[0] and \
                        neighbour_connection_point[1] > last_city_out_connection_point[1]) or \
                        (neighbour_connection_point[0] > last_city_out_connection_point[0] and \
                        neighbour_connection_point[1] < last_city_out_connection_point[1])) or \
                        (city_direction == 2 or city_direction == 3) and \
                        ((neighbour_connection_point[0] < last_city_out_connection_point[0] and \
                          neighbour_connection_point[1] < last_city_out_connection_point[1]) or \
                         (neighbour_connection_point[0] > last_city_out_connection_point[0] and \
                          neighbour_connection_point[1] > last_city_out_connection_point[1])):

                            new_line = connect_rail_in_grid_map(grid_map, city_out_connection_point,
                                                                next_neighbour_connection_point,
                                                                rail_trans, flip_start_node_trans=False,
                                                                flip_end_node_trans=False,
                                                                respect_transition_validity=False,
                                                                avoid_rail=True,
                                                                forbidden_cells=city_cells)
                            if len(new_line) == 0:
                                warnings.warn("[WARNING] No line added between stations")
                            elif new_line[-1] != next_neighbour_connection_point or new_line[
                                0] != city_out_connection_point:
                                warnings.warn("[WARNING] Unable to connect requested stations")
                            all_paths.extend(new_line)

                            new_line = connect_rail_in_grid_map(grid_map, last_city_out_connection_point,
                                                                neighbour_connection_point,
                                                                rail_trans, flip_start_node_trans=False,
                                                                flip_end_node_trans=False,
                                                                respect_transition_validity=False,
                                                                avoid_rail=True,
                                                                forbidden_cells=city_cells)
                            if len(new_line) == 0:
                                warnings.warn("[WARNING] No line added between stations")
                            elif new_line[-1] != neighbour_connection_point or new_line[
                                0] != last_city_out_connection_point:
                                warnings.warn("[WARNING] Unable to connect requested stations")
                            all_paths.extend(new_line)
                            set_of_connections.append(possible_connection)
                        else:

                            new_line = connect_rail_in_grid_map(grid_map, last_city_out_connection_point,
                                                                neighbour_connection_point,
                                                                rail_trans, flip_start_node_trans=False,
                                                                flip_end_node_trans=False,
                                                                respect_transition_validity=False,
                                                                avoid_rail=True,
                                                                forbidden_cells=city_cells)
                            if len(new_line) == 0:
                                warnings.warn("[WARNING] No line added between stations")
                            elif new_line[-1] != neighbour_connection_point or new_line[0] != last_city_out_connection_point:
                                warnings.warn("[WARNING] Unable to connect requested stations")
                            all_paths.extend(new_line)
                            set_of_connections.append(possible_connection)

                            new_line = connect_rail_in_grid_map(grid_map, city_out_connection_point,
                                                                next_neighbour_connection_point,
                                                                rail_trans, flip_start_node_trans=False,
                                                                flip_end_node_trans=False,
                                                                respect_transition_validity=False,
                                                                avoid_rail=True,
                                                                forbidden_cells=city_cells)
                            if len(new_line) == 0:
                                warnings.warn("[WARNING] No line added between stations")
                            elif new_line[-1] != next_neighbour_connection_point or new_line[0] != city_out_connection_point:
                                warnings.warn("[WARNING] Unable to connect requested stations")
                            all_paths.extend(new_line)
                    i += 1
        return all_paths

    def get_closest_neighbour_for_direction(self, closest_neighbours, out_direction):
        """
        Given a list of clostest neighbours in each direction this returns the city index of the neighbor in a given
        direction. Direction is a 90 degree cone facing the desired directiont.
        Exampe:
            North: The closes neighbour in the North direction is within the cone spanned by a line going
            North-West and North-East

        Parameters
        ----------
        closest_neighbours: List
            List of length 4 containing the index of closes neighbour in the corresponfing direction:
            [North-Neighbour, East-Neighbour, South-Neighbour, West-Neighbour]
        out_direction: int
            Direction we want to get city index from
            North: 0, East: 1, South: 2, West: 3

        Returns
        -------
        Returns the index of the closest neighbour in the desired direction. If none was present the neighbor clockwise
        or counter clockwise is returned
        """

        neighbour_idx = closest_neighbours[out_direction]
        if neighbour_idx is not None:
            return neighbour_idx

        neighbour_idx = closest_neighbours[(out_direction - 1) % 4]  # counter-clockwise
        if neighbour_idx is not None:
            return neighbour_idx

        neighbour_idx = closest_neighbours[(out_direction + 1) % 4]  # clockwise
        if neighbour_idx is not None:
            return neighbour_idx

        return closest_neighbours[(out_direction + 2) % 4]  # clockwise

    def _build_inner_cities(self, city_positions: IntVector2DArray, inner_connection_points: List[List[List[IntVector2D]]],
                            outer_connection_points: List[List[List[IntVector2D]]], rail_trans: RailEnvTransitions,
                            grid_map: GridTransitionMap) -> Tuple[List[IntVector2DArray], List[List[List[IntVector2D]]]]:
        """
        Set the parallel tracks within the city. The center track of the city is of the length of the city, the lenght
        of the tracks decrease by 2 for every parallel track away from the center
        EG:

                ---     Left Track
               -----    Center Track
                ---     Right Track

        Parameters
        ----------
        city_positions: IntVector2DArray
                        All coordinates of the cities

        inner_connection_points: List[List[List[IntVector2D]]]
            Points on city boarder that are used to generate inner city track
        outer_connection_points: List[List[List[IntVector2D]]]
            Points where the city is connected to neighboring cities
        rail_trans: RailEnvTransitions
            Railway transition objects
        grid_map: RailEnvTransitions
            The grid map containing the rails. Used to draw new rails

        Returns
        -------
        Returns a list of all the cells (Coordinates) that belong to a rail paths within the city.
        """

        free_rails: List[List[List[IntVector2D]]] = [[] for i in range(len(city_positions))]
        for current_city in range(len(city_positions)):

            # This part only works if we have keep same number of connection points for both directions
            # Also only works with two connection direction at each city
            for i in range(4):
                if len(inner_connection_points[current_city][i]) > 0:
                    boarder = i
                    break

            opposite_boarder = (boarder + 2) % 4
            nr_of_connection_points = len(inner_connection_points[current_city][boarder])
            number_of_out_rails = len(outer_connection_points[current_city][boarder])
            start_idx = int((nr_of_connection_points - number_of_out_rails) / 2)
            # Connect parallel tracks
            for track_id in range(nr_of_connection_points):
                source = inner_connection_points[current_city][boarder][track_id]
                target = inner_connection_points[current_city][opposite_boarder][track_id]
                current_track = connect_straight_line_in_grid_map(grid_map, source, target, rail_trans)
                free_rails[current_city].append(current_track)

            for track_id in range(nr_of_connection_points):
                source = inner_connection_points[current_city][boarder][track_id]
                target = inner_connection_points[current_city][opposite_boarder][track_id]

                # Connect parallel tracks with each other
                fix_inner_nodes(
                    grid_map, source, rail_trans)
                fix_inner_nodes(
                    grid_map, target, rail_trans)

                # Connect outer tracks to inner tracks
                if start_idx <= track_id < start_idx + number_of_out_rails:
                    source_outer = outer_connection_points[current_city][boarder][track_id - start_idx]
                    target_outer = outer_connection_points[current_city][opposite_boarder][track_id - start_idx]
                    connect_straight_line_in_grid_map(grid_map, source, source_outer, rail_trans)
                    connect_straight_line_in_grid_map(grid_map, target, target_outer, rail_trans)
        return free_rails

    def _set_trainstation_positions(self, city_positions: IntVector2DArray, city_radius: int,
                                    free_rails: List[List[List[IntVector2D]]]) -> List[List[Tuple[IntVector2D, int]]]:
        """
        Populate the cities with possible start and end positions. Trainstations are set on the center of each paralell
        track. Each trainstation gets a coordinate as well as number indicating what track it is on

        Parameters
        ----------
        city_positions: IntVector2DArray
                        All coordinates of the cities
        city_radius: int
            Radius of each city. Cities are squares with edge length 2 * city_radius + 1
        free_rails: List[List[List[IntVector2D]]]
            Cells that allow for trainstations to be placed

        Returns
        -------
        Returns a List[List[Tuple[IntVector2D, int]]] containing the coordinates of trainstations as well as their
        track number within the city
        """
        num_cities = len(city_positions)
        train_stations = [[] for i in range(num_cities)]
        for current_city in range(len(city_positions)):
            for track_nbr in range(len(free_rails[current_city])):
                possible_location = free_rails[current_city][track_nbr][
                    int(len(free_rails[current_city][track_nbr]) / 2)]
                train_stations[current_city].append((possible_location, track_nbr))
        return train_stations

    def _fix_transitions(self, city_cells: IntVector2DArray, inter_city_lines: List[IntVector2DArray],
                         grid_map: GridTransitionMap, vector_field):
        """
        Check and fix transitions of all the cells that were modified. This is necessary because we ignore validity
        while drawing the rails.

        Parameters
        ----------
        city_cells: IntVector2DArray
            Cells within cities. All of these might have changed and are thus checked
        inter_city_lines: List[IntVector2DArray]
            All cells within rails drawn between cities
        vector_field: IntVector2DArray
            Vectorfield of the size of the environment. It is used to generate preferred orienations for each cell.
            Each cell contains the prefered orientation of cells. If no prefered orientation is present it is set to -1
        grid_map: RailEnvTransitions
            The grid map containing the rails. Used to draw new rails

        """

        # Fix all cities with illegal transition maps
        rails_to_fix = np.zeros(3 * grid_map.height * grid_map.width * 2, dtype='int')
        rails_to_fix_cnt = 0
        cells_to_fix = city_cells + inter_city_lines
        for cell in cells_to_fix:
            cell_valid = grid_map.cell_neighbours_valid(cell, True)

            if not cell_valid:
                rails_to_fix[3 * rails_to_fix_cnt] = cell[0]
                rails_to_fix[3 * rails_to_fix_cnt + 1] = cell[1]
                rails_to_fix[3 * rails_to_fix_cnt + 2] = vector_field[cell]

                rails_to_fix_cnt += 1
        # Fix all other cells
        for cell in range(rails_to_fix_cnt):
            grid_map.fix_transitions((rails_to_fix[3 * cell], rails_to_fix[3 * cell + 1]), rails_to_fix[3 * cell + 2])

    def _closest_neighbour_in_grid4_directions(self, current_city_idx: int, city_positions: IntVector2DArray) -> List[int]:
        """
        Finds the closest city in each direction of the current city
        Parameters
        ----------
        current_city_idx: int
            Index of current city
        city_positions: IntVector2DArray
            Vector containing the coordinates of all cities

        Returns
        -------
        Returns indices of closest neighbour in every direction NESW
        """

        city_distances = []
        closest_neighbour: List[int] = [None for i in range(4)]

        # compute distance to all other cities
        for city_idx in range(len(city_positions)):
            city_distances.append(
                Vec2dOperations.get_manhattan_distance(city_positions[current_city_idx], city_positions[city_idx]))
        sorted_neighbours = np.argsort(city_distances)

        for neighbour in sorted_neighbours[1:]:  # do not include city itself
            direction_to_neighbour = direction_to_point(city_positions[current_city_idx], city_positions[neighbour])
            if closest_neighbour[direction_to_neighbour] is None:
                closest_neighbour[direction_to_neighbour] = neighbour

            # early return once all 4 directions have a closest neighbour
            if None not in closest_neighbour:
                return closest_neighbour

        return closest_neighbour

    @staticmethod
    def argsort(seq):
        """
        Same as Numpy sort but for lists
        Parameters
        ----------
        seq: List
            list that we would like to sort from smallest to largest

        Returns
        -------
        Returns the sorted list

        """
        # http://stackoverflow.com/questions/3071415/efficient-method-to-calculate-the-rank-vector-of-a-list-in-python
        return sorted(range(len(seq)), key=seq.__getitem__)

    def _get_cells_in_city(self, center: IntVector2D, radius: int, city_orientation: int,
                           vector_field: IntVector2DArray) -> IntVector2DArray:
        """
        Function the collect cells of a city. It also populates the vector field accoring to the orientation of the
        city.

        Example: City oriented north with a radius of 5, the vectorfield in the city will be as follows:
            |S|S|S|S|S|
            |S|S|S|S|S|
            |S|S|S|S|S|  <-- City center
            |N|N|N|N|N|
            |N|N|N|N|N|

        This is used to later orient the switches to avoid infeasible maps.

        Parameters
        ----------
        center: IntVector2D
            center coordinates of city
        radius: int
            radius of city (it is a square)
        city_orientation: int
            Orientation of city
        Returns
        -------
        flat list of all cell coordinates in the city

        """
        x_range = np.arange(center[0] - radius, center[0] + radius + 1)
        y_range = np.arange(center[1] - radius, center[1] + radius + 1)
        x_values = np.repeat(x_range, len(y_range))
        y_values = np.tile(y_range, len(x_range))
        city_cells = list(zip(x_values, y_values))
        for cell in city_cells:
            vector_field[cell] = align_cell_to_city(center, city_orientation, cell)
        return city_cells

    @staticmethod
    def _are_cities_overlapping(center_1, center_2, radius):
        """
        Check if two cities overlap. That is we check if two squares with certain edge length and position overlap
        Parameters
        ----------
        center_1: (int, int)
            Center of first city
        center_2: (int, int)
            Center of second city

        radius: int
            Radius of each city. Cities are squares with edge length 2 * city_radius + 1

        Returns
        -------
        Returns True if the cities overlap and False otherwise
        """
        return np.abs(center_1[0] - center_2[0]) < radius and np.abs(center_1[1] - center_2[1]) < radius

