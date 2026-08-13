"""Small deterministic starter catalog; operators may add reviewed records later."""

from uuid import UUID, uuid5

from recruitment_agent.domain.company import (
    CompanyAliasSeed,
    CompanyDomainSeed,
    CompanyEntityType,
    CompanySeed,
)

_COMPANY_NAMESPACE = UUID("5b347f65-5548-4f95-8226-4035824ac75e")


def company_seed_id(slug: str) -> UUID:
    return uuid5(_COMPANY_NAMESPACE, slug)


BYTEDANCE_ID = company_seed_id("bytedance")
TIKTOK_ID = company_seed_id("tiktok")
TENCENT_ID = company_seed_id("tencent")
ALIBABA_ID = company_seed_id("alibaba-group")
HUAWEI_ID = company_seed_id("huawei")
MEITUAN_ID = company_seed_id("meituan")
MICROSOFT_ID = company_seed_id("microsoft")
GOOGLE_ID = company_seed_id("google")
AMAZON_ID = company_seed_id("amazon")
APPLE_ID = company_seed_id("apple")
META_ID = company_seed_id("meta")
NVIDIA_ID = company_seed_id("nvidia")
NETFLIX_ID = company_seed_id("netflix")
TESLA_ID = company_seed_id("tesla")
UBER_ID = company_seed_id("uber")
AIRBNB_ID = company_seed_id("airbnb")
BAIDU_ID = company_seed_id("baidu")
JD_ID = company_seed_id("jd-com")
NETEASE_ID = company_seed_id("netease")
XIAOMI_ID = company_seed_id("xiaomi")
DIDI_ID = company_seed_id("didi-global")
KUAISHOU_ID = company_seed_id("kuaishou")
TRIP_COM_ID = company_seed_id("trip-com-group")
SHOPEE_ID = company_seed_id("shopee")
GRAB_ID = company_seed_id("grab")
REVOLUT_ID = company_seed_id("revolut")
WISE_ID = company_seed_id("wise")
MONZO_ID = company_seed_id("monzo")
DELIVEROO_ID = company_seed_id("deliveroo")
GOLDMAN_SACHS_ID = company_seed_id("goldman-sachs")
JPMORGAN_CHASE_ID = company_seed_id("jpmorgan-chase")
MORGAN_STANLEY_ID = company_seed_id("morgan-stanley")
HSBC_ID = company_seed_id("hsbc")
BARCLAYS_ID = company_seed_id("barclays")
BLOOMBERG_ID = company_seed_id("bloomberg")


COMMON_COMPANY_SEEDS: tuple[CompanySeed, ...] = (
    CompanySeed(
        id=BYTEDANCE_ID,
        canonical_name="ByteDance",
        display_name="ByteDance / 字节跳动",
        entity_type=CompanyEntityType.PARENT,
        aliases=(
            CompanyAliasSeed(alias="字节跳动", language="zh"),
            CompanyAliasSeed(alias="Byte Dance", language="en"),
        ),
        domains=(
            CompanyDomainSeed(domain="bytedance.com"),
            CompanyDomainSeed(domain="jobs.bytedance.com"),
        ),
    ),
    CompanySeed(
        id=TIKTOK_ID,
        canonical_name="TikTok",
        display_name="TikTok",
        entity_type=CompanyEntityType.BRAND,
        parent_company_id=BYTEDANCE_ID,
        aliases=(CompanyAliasSeed(alias="抖音海外版", language="zh"),),
        domains=(CompanyDomainSeed(domain="tiktok.com"),),
    ),
    CompanySeed(
        id=TENCENT_ID,
        canonical_name="Tencent",
        display_name="Tencent / 腾讯",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(
            CompanyAliasSeed(alias="腾讯", language="zh"),
            CompanyAliasSeed(alias="腾讯科技", language="zh"),
        ),
        domains=(
            CompanyDomainSeed(domain="tencent.com"),
            CompanyDomainSeed(domain="careers.tencent.com"),
        ),
    ),
    CompanySeed(
        id=ALIBABA_ID,
        canonical_name="Alibaba Group",
        display_name="Alibaba Group / 阿里巴巴集团",
        entity_type=CompanyEntityType.PARENT,
        aliases=(
            CompanyAliasSeed(alias="Alibaba", language="en"),
            CompanyAliasSeed(alias="阿里巴巴", language="zh"),
            CompanyAliasSeed(alias="阿里", language="zh"),
        ),
        domains=(CompanyDomainSeed(domain="alibaba.com"),),
    ),
    CompanySeed(
        id=HUAWEI_ID,
        canonical_name="Huawei",
        display_name="Huawei / 华为",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="华为", language="zh"),),
        domains=(CompanyDomainSeed(domain="huawei.com"),),
    ),
    CompanySeed(
        id=MEITUAN_ID,
        canonical_name="Meituan",
        display_name="Meituan / 美团",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="美团", language="zh"),),
        domains=(CompanyDomainSeed(domain="meituan.com"),),
    ),
    CompanySeed(
        id=MICROSOFT_ID,
        canonical_name="Microsoft",
        display_name="Microsoft / 微软",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="微软", language="zh"),),
        domains=(CompanyDomainSeed(domain="microsoft.com"),),
    ),
    CompanySeed(
        id=GOOGLE_ID,
        canonical_name="Google",
        display_name="Google / 谷歌",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="谷歌", language="zh"),),
        domains=(CompanyDomainSeed(domain="google.com"),),
    ),
    CompanySeed(
        id=AMAZON_ID,
        canonical_name="Amazon",
        display_name="Amazon / 亚马逊",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="亚马逊", language="zh"),),
        domains=(
            CompanyDomainSeed(domain="amazon.com"),
            CompanyDomainSeed(domain="amazon.jobs"),
        ),
    ),
    CompanySeed(
        id=APPLE_ID,
        canonical_name="Apple",
        display_name="Apple / 苹果",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="苹果", language="zh"),),
        domains=(CompanyDomainSeed(domain="apple.com"),),
    ),
    CompanySeed(
        id=META_ID,
        canonical_name="Meta",
        display_name="Meta",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(
            CompanyAliasSeed(alias="Meta Platforms", language="en"),
            CompanyAliasSeed(alias="Facebook", language="en"),
        ),
        domains=(
            CompanyDomainSeed(domain="meta.com"),
            CompanyDomainSeed(domain="facebook.com"),
        ),
    ),
    CompanySeed(
        id=NVIDIA_ID,
        canonical_name="NVIDIA",
        display_name="NVIDIA / 英伟达",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(
            CompanyAliasSeed(alias="Nvidia", language="en"),
            CompanyAliasSeed(alias="英伟达", language="zh"),
        ),
        domains=(CompanyDomainSeed(domain="nvidia.com"),),
    ),
    CompanySeed(
        id=NETFLIX_ID,
        canonical_name="Netflix",
        display_name="Netflix / 奈飞",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="奈飞", language="zh"),),
        domains=(CompanyDomainSeed(domain="netflix.com"),),
    ),
    CompanySeed(
        id=TESLA_ID,
        canonical_name="Tesla",
        display_name="Tesla / 特斯拉",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="特斯拉", language="zh"),),
        domains=(CompanyDomainSeed(domain="tesla.com"),),
    ),
    CompanySeed(
        id=UBER_ID,
        canonical_name="Uber",
        display_name="Uber / 优步",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="优步", language="zh"),),
        domains=(CompanyDomainSeed(domain="uber.com"),),
    ),
    CompanySeed(
        id=AIRBNB_ID,
        canonical_name="Airbnb",
        display_name="Airbnb / 爱彼迎",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="爱彼迎", language="zh"),),
        domains=(CompanyDomainSeed(domain="airbnb.com"),),
    ),
    CompanySeed(
        id=BAIDU_ID,
        canonical_name="Baidu",
        display_name="Baidu / 百度",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="百度", language="zh"),),
        domains=(CompanyDomainSeed(domain="baidu.com"),),
    ),
    CompanySeed(
        id=JD_ID,
        canonical_name="JD.com",
        display_name="JD.com / 京东",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(
            CompanyAliasSeed(alias="JD", language="en"),
            CompanyAliasSeed(alias="Jingdong", language="en"),
            CompanyAliasSeed(alias="京东", language="zh"),
            CompanyAliasSeed(alias="京东集团", language="zh"),
        ),
        domains=(CompanyDomainSeed(domain="jd.com"),),
    ),
    CompanySeed(
        id=NETEASE_ID,
        canonical_name="NetEase",
        display_name="NetEase / 网易",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="网易", language="zh"),),
        domains=(CompanyDomainSeed(domain="netease.com"),),
    ),
    CompanySeed(
        id=XIAOMI_ID,
        canonical_name="Xiaomi",
        display_name="Xiaomi / 小米",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="小米", language="zh"),),
        domains=(CompanyDomainSeed(domain="xiaomi.com"),),
    ),
    CompanySeed(
        id=DIDI_ID,
        canonical_name="Didi Global",
        display_name="DiDi / 滴滴",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(
            CompanyAliasSeed(alias="DiDi", language="en"),
            CompanyAliasSeed(alias="滴滴", language="zh"),
            CompanyAliasSeed(alias="滴滴出行", language="zh"),
        ),
        domains=(CompanyDomainSeed(domain="didiglobal.com"),),
    ),
    CompanySeed(
        id=KUAISHOU_ID,
        canonical_name="Kuaishou",
        display_name="Kuaishou / 快手",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="快手", language="zh"),),
        domains=(CompanyDomainSeed(domain="kuaishou.com"),),
    ),
    CompanySeed(
        id=TRIP_COM_ID,
        canonical_name="Trip.com Group",
        display_name="Trip.com Group / 携程集团",
        entity_type=CompanyEntityType.PARENT,
        aliases=(
            CompanyAliasSeed(alias="Ctrip", language="en"),
            CompanyAliasSeed(alias="携程", language="zh"),
            CompanyAliasSeed(alias="携程集团", language="zh"),
        ),
        domains=(
            CompanyDomainSeed(domain="trip.com"),
            CompanyDomainSeed(domain="ctrip.com"),
        ),
    ),
    CompanySeed(
        id=SHOPEE_ID,
        canonical_name="Shopee",
        display_name="Shopee / 虾皮",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="虾皮", language="zh"),),
        domains=(CompanyDomainSeed(domain="shopee.com"),),
    ),
    CompanySeed(
        id=GRAB_ID,
        canonical_name="Grab",
        display_name="Grab",
        entity_type=CompanyEntityType.EMPLOYER,
        domains=(CompanyDomainSeed(domain="grab.com"),),
    ),
    CompanySeed(
        id=REVOLUT_ID,
        canonical_name="Revolut",
        display_name="Revolut",
        entity_type=CompanyEntityType.EMPLOYER,
        domains=(CompanyDomainSeed(domain="revolut.com"),),
    ),
    CompanySeed(
        id=WISE_ID,
        canonical_name="Wise",
        display_name="Wise",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="TransferWise", language="en"),),
        domains=(CompanyDomainSeed(domain="wise.com"),),
    ),
    CompanySeed(
        id=MONZO_ID,
        canonical_name="Monzo",
        display_name="Monzo",
        entity_type=CompanyEntityType.EMPLOYER,
        domains=(CompanyDomainSeed(domain="monzo.com"),),
    ),
    CompanySeed(
        id=DELIVEROO_ID,
        canonical_name="Deliveroo",
        display_name="Deliveroo",
        entity_type=CompanyEntityType.EMPLOYER,
        domains=(
            CompanyDomainSeed(domain="deliveroo.com"),
            CompanyDomainSeed(domain="deliveroo.co.uk"),
        ),
    ),
    CompanySeed(
        id=GOLDMAN_SACHS_ID,
        canonical_name="Goldman Sachs",
        display_name="Goldman Sachs / 高盛",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(
            CompanyAliasSeed(alias="Goldman", language="en"),
            CompanyAliasSeed(alias="高盛", language="zh"),
        ),
        domains=(CompanyDomainSeed(domain="goldmansachs.com"),),
    ),
    CompanySeed(
        id=JPMORGAN_CHASE_ID,
        canonical_name="JPMorgan Chase",
        display_name="JPMorgan Chase / 摩根大通",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(
            CompanyAliasSeed(alias="JPMorgan", language="en"),
            CompanyAliasSeed(alias="J.P. Morgan", language="en"),
            CompanyAliasSeed(alias="JP Morgan", language="en"),
            CompanyAliasSeed(alias="摩根大通", language="zh"),
        ),
        domains=(CompanyDomainSeed(domain="jpmorgan.com"),),
    ),
    CompanySeed(
        id=MORGAN_STANLEY_ID,
        canonical_name="Morgan Stanley",
        display_name="Morgan Stanley / 摩根士丹利",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="摩根士丹利", language="zh"),),
        domains=(CompanyDomainSeed(domain="morganstanley.com"),),
    ),
    CompanySeed(
        id=HSBC_ID,
        canonical_name="HSBC",
        display_name="HSBC / 汇丰",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(
            CompanyAliasSeed(alias="HSBC Holdings", language="en"),
            CompanyAliasSeed(alias="汇丰", language="zh"),
        ),
        domains=(CompanyDomainSeed(domain="hsbc.com"),),
    ),
    CompanySeed(
        id=BARCLAYS_ID,
        canonical_name="Barclays",
        display_name="Barclays / 巴克莱",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="巴克莱", language="zh"),),
        domains=(CompanyDomainSeed(domain="barclays.com"),),
    ),
    CompanySeed(
        id=BLOOMBERG_ID,
        canonical_name="Bloomberg",
        display_name="Bloomberg / 彭博",
        entity_type=CompanyEntityType.EMPLOYER,
        aliases=(CompanyAliasSeed(alias="彭博", language="zh"),),
        domains=(
            CompanyDomainSeed(domain="bloomberg.com"),
            CompanyDomainSeed(domain="bloomberg.net"),
        ),
    ),
)
