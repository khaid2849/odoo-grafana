import { Component, onWillStart, useState } from "@odoo/owl";
import { cookie } from "@web/core/browser/cookie";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";

export class GrafanaEmbed extends Component {
    static template = "grafana.GrafanaEmbed";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.state = useState({ dashboards: [], activeId: null, loading: true });

        onWillStart(async () => {
            const config = await this.orm.call("grafana.dashboard", "get_embed_config", []);
            this.state.dashboards = config.dashboards;
            const requested = this.props.action.context?.dashboard_id;
            const initial = config.dashboards.find((d) => d.id === requested) || config.dashboards[0];
            this.state.activeId = initial?.id || null;
            this.state.loading = false;
        });
    }

    get activeDashboard() {
        return this.state.dashboards.find((d) => d.id === this.state.activeId);
    }

    get iframeUrl() {
        const dashboard = this.activeDashboard;
        if (!dashboard) {
            return "";
        }
        const theme = cookie.get("color_scheme") === "dark" ? "dark" : "light";
        return `${dashboard.url}&theme=${theme}`;
    }

    selectDashboard(dashboardId) {
        this.state.activeId = dashboardId;
    }
}

registry.category("actions").add("grafana.embed", GrafanaEmbed);
