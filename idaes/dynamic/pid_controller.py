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
PID controller block
"""

__author__ = "John Eslick"

import pyomo.environ as pyo

from idaes.core import ProcessBlockData, declare_process_block_class
from pyomo.common.config import ConfigValue, In
from idaes.core.util.math import smooth_max, smooth_min
from idaes.core.util.exceptions import ConfigurationError

@declare_process_block_class("PIDBlock", doc=
    """This is a PID controller block. The PID Controller block must be added
after the DAE transformation.""")
class PIDBlockData(ProcessBlockData):
    CONFIG = ProcessBlockData.CONFIG()
    CONFIG.declare("pv", ConfigValue(
        default=None,
        description="Measured process variable",
        doc="A Pyomo Var, Expression, or Reference for the measured"
            " process variable. Should be indexed by time."))
    CONFIG.declare("output", ConfigValue(
        default=None,
        description="Controlled process variable",
        doc="A Pyomo Var, Expression, or Reference for the controlled"
            " process variable. Should be indexed by time."))
    CONFIG.declare("upper", ConfigValue(
        default=1.0,
        domain=float,
        description="Output upper limit",
        doc="The upper limit for the controller output, default=1"))
    CONFIG.declare("lower", ConfigValue(
        default=0.0,
        domain=float,
        description="Output lower limit",
        doc="The lower limit for the controller output, default=0"))
    CONFIG.declare("calculate_initial_integral", ConfigValue(
        default=True,
        domain=bool,
        description="Calculate the initial integral term value if true, "
                    " otherwise provide a variable err_i0, which can be fixed",
        doc="Calculate the initial integral term value if true, otherwise"
            " provide a variable err_i0, which can be fixed, default=True"))
    # other options can be added, but this covers the bare minimum

    def build(self):
        """
        Build the PID block
        """
        super().build() # do the ProcessBlockData voodoo for config
        # Check for required config
        if self.config.pv is None:
            raise ConfigurationError("Controller configuration requires 'pv'")
        if self.config.output is None:
            raise ConfigurationError("Controller configuration requires 'output'")
        # Shorter pointers to time set information
        time_set = self.flowsheet().time
        t0 = time_set.first()
        # Variable for basic controller settings may change with time.
        self.setpoint = pyo.Var(time_set, doc="Setpoint")
        self.gain = pyo.Var(time_set, doc="Controller gain")
        self.time_i = pyo.Var(time_set, doc="Integral time")
        self.time_d = pyo.Var(time_set, doc="Derivative time")
        # Make the initial derivative term a variable so you can set it. This
        # should let you carry on from the end of another time period
        self.err_d0 = pyo.Var(doc="Initial derivative term", initialize=0)
        self.err_d0.fix()
        if not self.config.calculate_initial_integral:
            self.err_i0 = pyo.Var(doc="Initial integral term", initialize=0)
            self.err_i0.fix()
        # Make refernces to the output and measured variables
        self.pv = pyo.Reference(self.config.pv) # No duplicate
        self.output = pyo.Reference(self.config.output) # No duplicate
        # Create an expression for error from setpoint
        @self.Expression(time_set, doc="Setpoint error")
        def err(b, t):
            return  self.setpoint[t] - self.pv[t]
        # Use expressions to allow the some future configuration
        @self.Expression(time_set)
        def pterm(b,t):
            return -self.pv[t]
        @self.Expression(time_set)
        def dterm(b,t):
            return -self.pv[t]
        @self.Expression(time_set)
        def iterm(b,t):
            return self.err[t]
        # Output limits parameter
        self.limits = pyo.Param(["l", "h"], mutable=True,
            doc="controller output limits",
            initialize={
                "l":self.config.lower,
                "h":self.config.upper})
        # Smooth min and max are used to limit output, smoothing parmeter here
        self.smooth_eps = pyo.Param(mutable=True, initialize=1e-4,
            doc="Smoothing parameter for controler output limits")
        # This is ugly, but want integral and derivative error as expressions,
        # nice implimentation with variables is harder to initialize and solve
        @self.Expression(time_set, doc="Derivative error.")
        def err_d(b, t):
            if t == t0:
                return self.err_d0
            else:
                return (b.dterm[t] - b.dterm[time_set.prev(t)])\
                       /(t - time_set.prev(t))
        # Want to fix the output varaible at the first time step to make
        # solving easier. This calculates the initial integral error to line up
        # with the initial output value, keeps the controller from initially
        # jumping.
        if self.config.calculate_initial_integral:
            @self.Expression(doc="Initial integral error")
            def err_i0(b):
                return b.time_i[t0]*(b.output[0] - b.gain[t0]*b.pterm[t0]\
                       - b.gain[t0]*b.time_d[t0]*b.err_d[t0])/b.gain[t0]
        # integral error
        @self.Expression(time_set, doc="Integral error")
        def err_i(b, t_end):
            return b.err_i0 + sum((b.iterm[t] + b.iterm[time_set.prev(t)])
                                   *(t - time_set.prev(t))/2.0
                                  for t in time_set if t <= t_end and t > t0)
        # Calculate the unconstrainted contoller output
        @self.Expression(time_set, doc="Unconstrained contorler output")
        def unconstrained_output(b, t):
            return b.gain[t]*(b.pterm[t] +
                              1.0/b.time_i[t]*b.err_i[t] +
                              b.time_d[t]*b.err_d[t])
        # Add the controller output constraint and limit it with smooth min/max
        e = self.smooth_eps
        h = self.limits["h"]
        l = self.limits["l"]
        @self.Constraint(time_set, doc="Controller output constraint")
        def output_constraint(b, t):
            if t == t0:
                return pyo.Constraint.Skip
            else:
                return self.output[t] ==\
                    smooth_min(
                        smooth_max(self.unconstrained_output[t], l, e), h, e)
