import { Heading } from "../../components/Heading";
import { configNames } from "../../constants";
import { AccessManagement } from "./AccessManagement";
import { FilesConfiguration } from "./FilesConfiguration";
import { MasterDataConfig } from "./MasterDataConfig";
import { PhasingConfig } from "./PhasingConfig";
import { RoleDefinitions } from "./RoleDefinitions";
import { TacticsConfig } from "./TacticsConfig";
import { type Bootstrap, type ConfigTab } from "../../types";

export function Configuration(props: {
  activeTab: ConfigTab;
  setActiveTab: (tab: ConfigTab) => void;
  isSystemAdmin: boolean;
  canEditConfiguration: boolean;
  canManageTactics: boolean;
  bootstrap: Bootstrap;
  flash: (message: string) => void;
  setError: (message: string) => void;
  refresh: () => void;
}) {
  const tabs: ConfigTab[] = props.isSystemAdmin
    ? ["access", "roles", "tactics", "phasing", "files", "customer", "product"]
    : props.canEditConfiguration ? ["access", "tactics", "phasing"] : ["access"];
  return <>
    <Heading title="Configuration" />
    <nav className="config-tabs" aria-label="Configuration sections">
      {tabs.map((tab) => <button
        aria-current={props.activeTab === tab ? "page" : undefined}
        className={`button ${props.activeTab === tab ? "tab-active" : ""}`}
        key={tab}
        onClick={() => props.setActiveTab(tab)}
      >{configNames[tab]}</button>)}
    </nav>
    {props.activeTab === "access" && <AccessManagement {...props} />}
    {(props.activeTab === "customer" || props.activeTab === "product") &&
      <MasterDataConfig {...props} type={props.activeTab} />}
    {props.activeTab === "tactics" && props.canManageTactics && <TacticsConfig {...props} />}
    {props.activeTab === "phasing" && props.canManageTactics && <PhasingConfig {...props} />}
    {props.activeTab === "files" && <FilesConfiguration {...props} />}
    {props.activeTab === "roles" && props.isSystemAdmin && <RoleDefinitions {...props} />}
  </>;
}
