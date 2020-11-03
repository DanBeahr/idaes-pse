##############################################################################
# Institute for the Design of Advanced Energy Systems Process Systems
# Engineering Framework (IDAES PSE Framework) Copyright (c) 2018-2019, by the
# software owners: The Regents of the University of California, through
# Lawrence Berkeley National Laboratory,  National Technology & Engineering
# Solutions of Sandia, LLC, Carnegie Mellon University, West Virginia
# University Research Corporation, et al. All rights reserved.
#
# Please see the files COPYRIGHT.txt and LICENSE.txt for full copyright and
# license information, respectively. Both files are also available online
# at the URL "https://github.com/IDAES/idaes-pse".
##############################################################################
"""
NTU Condenser model, for use with Helmholtz EOS property packages.
"""

__author__ = "Jinliang Ma"

# Import Pyomo libraries
import pyomo.environ as pyo
from pyomo.common.config import ConfigBlock, ConfigValue, In
# Import IDAES cores
from idaes.core import declare_process_block_class, UnitModelBlockData
from idaes.core.util import from_json, to_json, StoreSpec
from idaes.core.util.tables import create_stream_table_dataframe
from idaes.core.util.misc import add_object_reference
from idaes.generic_models.unit_models.heater import (
    _make_heater_config_block, _make_heater_control_volume)
import idaes.core.util.unit_costing as costing
import idaes.core.util.scaling as iscale
import idaes.logger as idaeslog


def _make_heat_exchanger_config(config):
    """
    Declare configuration options for HeatExchangerData block.
    """
    config.declare(
        "hot_side_name",
        ConfigValue(
            default="shell",
            domain=str,
            doc="Hot side name, sets control volume and inlet and outlet names",
        ),
    )
    config.declare(
        "cold_side_name",
        ConfigValue(
            default="tube",
            domain=str,
            doc="Cold side name, sets control volume and inlet and outlet names",
        ),
    )
    config.declare(
        "hot_side_config",
        ConfigBlock(
            implicit=True,
            description="Config block for hot side",
            doc="""A config block used to construct the hot side control volume.
This config can be given by the hot side name instead of hot_side_config.""",
        ),
    )
    config.declare(
        "cold_side_config",
        ConfigBlock(
            implicit=True,
            description="Config block for cold side",
            doc="""A config block used to construct the cold side control volume.
This config can be given by the cold side name instead of cold_side_config.""",
        ),
    )
    _make_heater_config_block(config.hot_side_config)
    _make_heater_config_block(config.cold_side_config)


@declare_process_block_class("HelmNtuCondenser", doc="Simple 0D condenser model.")
class HelmNtuCondenserData(UnitModelBlockData):
    """
    Simple NTU condenser unit model.  This model assumes the property pacakages
    specified are Helmholtz EOS type.
    """
    CONFIG = UnitModelBlockData.CONFIG(implicit=True)
    _make_heat_exchanger_config(CONFIG)

    def _process_config(self):
        """Check for configuration errors and alternate config option names.
        """
        config = self.config

        if config.hot_side_name == config.cold_side_name:
            raise NameError(
                "Condenser hot and cold side cannot have the same name '{}'."
                " Be sure to set both the hot_side_name and cold_side_name.".format(
                    config.hot_side_name
                )
            )
        for o in config:
            if not (
                o in self.CONFIG or o in [config.hot_side_name, config.cold_side_name]
            ):
                raise KeyError("Condenser config option {} not defined".format(o))

        if config.hot_side_name in config:
            config.hot_side_config.set_value(config[config.hot_side_name])
            # Allow access to hot_side_config under the hot_side_name
            setattr(config, config.hot_side_name, config.hot_side_config)
        if config.cold_side_name in config:
            config.cold_side_config.set_value(config[config.cold_side_name])
            # Allow access to hot_side_config under the cold_side_name
            setattr(config, config.cold_side_name, config.cold_side_config)

    def build(self):
        """
        Building model

        Args:
            None
        Returns:
            None
        """
        ########################################################################
        #  Call UnitModel.build to setup dynamics and configure                #
        ########################################################################
        super().build()
        self._process_config()
        config = self.config
        time = self.flowsheet().config.time

        ########################################################################
        # Add variables                                                        #
        ########################################################################
        units_meta = self.config.property_package.get_metadata()
        self.overall_heat_transfer_coefficient = pyo.Var(
            time,
            domain=pyo.PositiveReals,
            initialize=100.0,
            doc="Overall heat transfer coefficient",
            units=units_meta.get_derived_units("heat_trasnfer_coefficient")
        )
        self.area = pyo.Var(
            domain=pyo.PositiveReals,
            initialize=1000.0,
            doc="Heat exchange area",
            units=units_meta.get_derived_units("area")
        )

        ########################################################################
        # Add control volumes                                                  #
        ########################################################################
        hot_side = _make_heater_control_volume(
            self,
            config.hot_side_name,
            config.hot_side_config,
            dynamic=config.dynamic,
            has_holdup=config.has_holdup,
        )
        cold_side = _make_heater_control_volume(
            self,
            config.cold_side_name,
            config.cold_side_config,
            dynamic=config.dynamic,
            has_holdup=config.has_holdup,
        )
        # Add refernces to the hot side and cold side, so that we have solid
        # names to refere to internally.  side_1 and side_2 also maintain
        # compatability with older models.  Using add_object_reference keeps
        # these from showing up when you iterate through pyomo compoents in a
        # model, so only the user specified control volume names are "seen"
        if not hasattr(self, "side_1"):
            add_object_reference(self, "side_1", hot_side)
        if not hasattr(self, "side_2"):
            add_object_reference(self, "side_2", cold_side)
        if not hasattr(self, "hot_side"):
            add_object_reference(self, "hot_side", hot_side)
        if not hasattr(self, "cold_side"):
            add_object_reference(self, "cold_side", cold_side)

        ########################################################################
        # Add ports                                                            #
        ########################################################################
        i1 = self.add_inlet_port(
            name=f"{config.hot_side_name}_inlet",
            block=self.side_1,
            doc="Hot side inlet")
        i2 = self.add_inlet_port(
            name=f"{config.cold_side_name}_inlet",
            block=self.side_2,
            doc="Cold side inlet")
        o1 = self.add_outlet_port(
            name=f"{config.hot_side_name}_outlet",
            block=self.side_1,
            doc="Hot side outlet")
        o2 = self.add_outlet_port(
            name=f"{config.cold_side_name}_outlet",
            block=self.side_2,
            doc="Cold side outlet")

        # Using Andrew's function for now.  I want these port names for backward
        # compatablity, but I don't want them to appear if you iterate throught
        # components and add_object_reference hides them from Pyomo.
        if not hasattr(self, "inlet_1"):
            add_object_reference(self, "inlet_1", i1)
        if not hasattr(self, "inlet_2"):
            add_object_reference(self, "inlet_2", i2)
        if not hasattr(self, "outlet_1"):
            add_object_reference(self, "outlet_1", o1)
        if not hasattr(self, "outlet_2"):
            add_object_reference(self, "outlet_2", o2)

        if not hasattr(self, "hot_inlet"):
            add_object_reference(self, "hot_inlet", i1)
        if not hasattr(self, "cold_inlet"):
            add_object_reference(self, "cold_inlet", i2)
        if not hasattr(self, "hot_outlet"):
            add_object_reference(self, "hot_outlet", o1)
        if not hasattr(self, "cold_outlet"):
            add_object_reference(self, "cold_outlet", o2)

        ########################################################################
        # Add a unit level energy balance                                      #
        ########################################################################
        @self.Constraint(time, doc="Heat balance equation")
        def unit_heat_balance(b, t):
            return 0 == self.side_1.heat[t] + self.side_2.heat[t]

        ########################################################################
        # Add some useful expressions for condenser performance                #
        ########################################################################

        @self.Expression(time, doc="Inlet temperature difference")
        def delta_temperature_in(b, t):
                return (b.side_1.properties_in[t].temperature
                    - b.side_2.properties_in[t].temperature)

        @self.Expression(time, doc="Outlet temperature difference")
        def delta_temperature_out(b, t):
                return (b.side_1.properties_out[t].temperature
                    - b.side_2.properties_out[t].temperature)

        @self.Expression(time, doc="NTU Based temperature difference")
        def delta_temperature_ntu(b, t):
                return (b.side_1.properties_in[t].temperature_sat -
                    b.side_2.properties_in[t].temperature)

        @self.Expression(time, doc="Minimum product of flow rate and heat "
            "capacity (always on tube side since shell side has phase change)")
        def mcp_min(b, t):
            return (self.side_2.properties_in[t].flow_mol
                * self.side_2.properties_in[t].cp_mol_phase['Liq'])

        @self.Expression(time, doc="Number of transfer units (NTU)")
        def ntu(b, t):
            return b.overall_heat_transfer_coefficient[t]*b.area/b.mcp_min[t]

        @self.Expression(time, doc="Condenser effectiveness factor")
        def effectiveness(b, t):
            return 1 - pyo.exp(-self.ntu[t])

        @self.Expression(time, doc="Heat treansfer")
        def heat_transfer(b, t):
            return b.effectiveness[t]*b.mcp_min[t] * (
                b.side_1.properties_in[t].temperature_sat
                - b.side_2.properties_in[t].temperature)

        ########################################################################
        # Add Equations to calculate heat duty based on NTU method             #
        ########################################################################
        @self.Constraint(
            time, doc="Heat transfer rate equation based on NTU method")
        def heat_transfer_equation(b, t):
            return self.side_2.heat[t] == self.heat_transfer[t]

        @self.Constraint(
            time, doc="Shell side outlet enthalpy is saturated water enthalpy")
        def saturation_eqn(b, t):
            return (self.side_1.properties_out[t].enth_mol ==
                self.side_1.properties_in[t].enth_mol_sat_phase["Liq"])

    def set_initial_condition(self):
        if self.config.dynamic is True:
            self.side_1.material_accumulation[:,:,:].value = 0
            self.side_1.energy_accumulation[:,:].value = 0
            self.side_1.material_accumulation[0,:,:].fix(0)
            self.side_1.energy_accumulation[0,:].fix(0)
            self.side_2.material_accumulation[:,:,:].value = 0
            self.side_2.energy_accumulation[:,:].value = 0
            self.side_2.material_accumulation[0,:,:].fix(0)
            self.side_2.energy_accumulation[0,:].fix(0)

    def initialize(
        blk,
        state_args_1=None,
        state_args_2=None,
        unfix='hot_flow',
        outlvl=idaeslog.NOTSET,
        solver="ipopt",
        optarg={"tol": 1e-6, "max_iter": 50},
    ):
        """
        Condenser initialization method. The initialization routine assumes
        fixed area and heat transfer coefficient and adjusts the cooling water
        flow to condense steam to saturated water at shell side pressure.

        Args:
            state_args_1 : a dict of arguments to be passed to the property
                initialization for side_1 (see documentation of the specific
                property package) (default = None).
            state_args_2 : a dict of arguments to be passed to the property
                initialization for side_2 (see documentation of the specific
                property package) (default = None).
            optarg : solver options dictionary object (default={'tol': 1e-6})
            solver : str indicating which solver to use during
                     initialization (default = 'ipopt')

        Returns:
            None

        """
        if unfix not in {"hot_flow", "cold_flow", "pressure"}:
            raise Exception("Condenser free variable must be in 'hot_flow', "
                "'cold_flow', or 'pressure'")
        # Set solver options
        init_log = idaeslog.getInitLogger(blk.name, outlvl, tag="unit")
        solve_log = idaeslog.getSolveLogger(blk.name, outlvl, tag="unit")

        # Store initial model specs, restored at the end of initializtion, so
        # the problem is not altered.  This can restore fixed/free vars,
        # active/inactive constraints, and fixed variable values.
        sp = StoreSpec.value_isfixed_isactive(only_fixed=True)
        istate = to_json(blk, return_dict=True, wts=sp)

        opt = pyo.SolverFactory(solver)
        opt.options = optarg

        flags1 = blk.side_1.initialize(
            outlvl=outlvl, optarg=optarg, solver=solver, state_args=state_args_1)
        flags2 = blk.side_2.initialize(
            outlvl=outlvl, optarg=optarg, solver=solver, state_args=state_args_2)
        init_log.info_high("Initialization Step 1 Complete.")

        # Solve with all constraints activated
        blk.saturation_eqn.activate()
        if unfix == 'pressure':
            blk.hot_side.properties_in[0].pressure.unfix()
        elif unfix == 'hot_flow':
            blk.hot_side.properties_in[0].flow_mol.unfix()
        elif unfix == 'cold_flow':
            blk.cold_side.properties_in[0].flow_mol.unfix()

        with idaeslog.solver_log(solve_log, idaeslog.DEBUG) as slc:
            res = opt.solve(blk, tee=slc.tee)
        init_log.info_high(
            "Initialization Step 4 {}.".format(idaeslog.condition(res))
        )

        # Release Inlet state
        blk.side_1.release_state(flags1, outlvl + 1)
        blk.side_2.release_state(flags2, outlvl + 1)
        from_json(blk, sd=istate, wts=sp)



    def _get_performance_contents(self, time_point=0):
        var_dict = {
            "HX Coefficient": self.overall_heat_transfer_coefficient[time_point]
        }
        var_dict["HX Area"] = self.area
        var_dict["Heat Duty"] = self.heat_duty[time_point]
        expr_dict = {}
        expr_dict["Delta T In"] = self.delta_temperature_in[time_point]
        expr_dict["Delta T Out"] = self.delta_temperature_out[time_point]

        return {"vars": var_dict, "exprs": expr_dict}

    def _get_stream_table_contents(self, time_point=0):
        return create_stream_table_dataframe(
            {
                "Hot Inlet": self.hot_inlet,
                "Hot Outlet": self.hot_outlet,
                "Cold Inlet": self.cold_inlet,
                "Cold Outlet": self.cold_outlet,
            },
            time_point=time_point,
        )

    def get_costing(self, module=costing):
        if not hasattr(self.flowsheet(), "costing"):
            self.flowsheet().get_costing()
        self.costing = pyo.Block()

        module.hx_costing(self.costing)

    def calculate_scaling_factors(self):
        super().calculate_scaling_factors()

        area_sf_default = 1e-2
        overall_heat_transfer_coefficient_sf_default = 1e-2

        # Function to set defaults so I don't need to reproduce the same code
        def _fill_miss_with_default(name, s):
            try:
                c = getattr(self, name)
            except AttributeError:
                return # it's okay if the attribute doesn't exist, spell careful
            if iscale.get_scaling_factor(c) is None:
                for ci in c.values():
                    if iscale.get_scaling_factor(ci) is None:
                        iscale.set_scaling_factor(ci, s)

        # Set defaults where scale factors are missing
        _fill_miss_with_default("area", area_sf_default)
        _fill_miss_with_default(
            "overall_heat_transfer_coefficient",
             overall_heat_transfer_coefficient_sf_default
        )

        for t, c in self.heat_transfer_equation.items():
            sf = iscale.get_scaling_factor(self.cold_side.heat[t])
            iscale.constraint_scaling_transform(c, sf)

        for t, c in self.unit_heat_balance.items():
            sf = iscale.get_scaling_factor(self.cold_side.heat[t])
            iscale.constraint_scaling_transform(c, sf)

        for t, c in self.saturation_eqn.items():
            sf = iscale.get_scaling_factor(
                self.hot_side.properties_out[t].enth_mol)
            iscale.constraint_scaling_transform(c, sf)
