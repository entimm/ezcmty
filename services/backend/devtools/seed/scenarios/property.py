from dataclasses import dataclass

from devtools.seed.runtime import Actor, Executor


@dataclass(frozen=True)
class Company:
    index: int
    id: str
    name: str
    login: str
    communities: tuple[str, ...]


def provision(executor: Executor, actor: Actor, index: int, parameters: dict[str, int]) -> Company:
    key = f"property/{index}"
    prefix = f"seed_{executor.state.run_id}_c{index}"
    name = f"演示物业 {executor.state.run_id[:8]}-{index + 1}"
    values = {"code": prefix.upper(), "name": name}
    company = executor.step(
        key,
        actor,
        "property.company.create",
        "company",
        values,
        unique={"code": prefix.upper()},
        expected={**values, "enabled": False},
    )
    communities: list[str] = []
    for number in range(parameters["communities_per_company"]):
        community_values = {
            "property_company_id": company,
            "code": f"{prefix}_s{number}".upper(),
            "name": f"演示小区 {number + 1}",
            "address": f"演示路 {number + 1} 号",
        }
        communities.append(
            executor.step(
                key + f"/community/{number}",
                actor,
                "property.community.create",
                "community",
                community_values,
                unique={"code": community_values["code"]},
                expected={**community_values, "enabled": True},
            )
        )
    for number in range(parameters["admins_per_company"]):
        login = f"{prefix}_a{number}"
        executor.create_account(
            key + f"/account/{number}",
            actor,
            login,
            f"物业演示账号 {index + 1}-{number + 1}",
            "property",
            company_id=company,
            company_name=name,
        )
    executor.step(
        key + "/enable",
        actor,
        "property.company.update",
        "company",
        {"enabled": True},
        identifier=company,
        expected={"enabled": True},
    )
    for number in range(parameters["admins_per_company"]):
        login = f"{prefix}_a{number}"
        record = executor.repo.account("property_admin", login)
        assert record is not None
        if number % 3 != 1:
            executor.change_password(
                key + f"/account/{number}/password", record.id, "property_admin", login
            )
        if number % 3 == 2:
            executor.step(
                key + f"/account/{number}/disable",
                actor,
                "property.admin.update",
                "account",
                {"enabled": False},
                identifier=record.id,
                refs={"company_id": company},
                expected={"enabled": False},
            )
    return Company(index, company, name, f"{prefix}_a0", tuple(communities))


def finalize(executor: Executor, actor: Actor, company: Company, companies: int) -> None:
    if len(company.communities) > 1:
        executor.step(
            f"property/{company.index}/community/disable",
            actor,
            "property.community.update",
            "community",
            {"enabled": False},
            identifier=company.communities[-1],
            expected={"enabled": False},
        )
    if companies > 1 and company.index == companies - 1:
        executor.step(
            f"property/{company.index}/disable",
            actor,
            "property.company.update",
            "company",
            {"enabled": False},
            identifier=company.id,
            expected={"enabled": False},
        )
