"""Deterministic reviewed employer catalog.

The catalog is split into the original foundation seeds and the reviewed
China internet major expansion. Together they must keep globally unique
normalized canonical names, aliases, and domains, because Phase 4.5
resolution performs exact matching only.
"""

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


_FOUNDATION_COMPANY_SEEDS: tuple[CompanySeed, ...] = (
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


def _seed(
    slug: str,
    canonical_name: str,
    display_name: str,
    *,
    zh: tuple[str, ...] = (),
    en: tuple[str, ...] = (),
    domains: tuple[str, ...] = (),
    entity_type: CompanyEntityType = CompanyEntityType.EMPLOYER,
    parent_company_id: UUID | None = None,
) -> CompanySeed:
    """Compact reviewed-record constructor for the China internet catalog."""
    return CompanySeed(
        id=company_seed_id(slug),
        canonical_name=canonical_name,
        display_name=display_name,
        entity_type=entity_type,
        parent_company_id=parent_company_id,
        aliases=(
            *(CompanyAliasSeed(alias=alias, language="zh") for alias in zh),
            *(CompanyAliasSeed(alias=alias, language="en") for alias in en),
        ),
        domains=tuple(CompanyDomainSeed(domain=domain) for domain in domains),
    )


#: Reviewed expansion covering mainstream China internet employers. Together
#: with the 13 China entries already present in the foundation catalog
#: (ByteDance, TikTok, Tencent, Alibaba Group, Huawei, Meituan, Baidu, JD.com,
#: NetEase, Xiaomi, DiDi, Kuaishou, Trip.com Group) this yields 100 reviewed
#: China internet majors.
CHINA_INTERNET_MAJOR_SEEDS: tuple[CompanySeed, ...] = (
    # --- Major-group subsidiaries and brands that recruit under their own name.
    _seed(
        "ant-group",
        "Ant Group",
        "Ant Group / 蚂蚁集团",
        zh=("蚂蚁集团", "蚂蚁金服", "支付宝"),
        en=("Alipay",),
        domains=("antgroup.com", "alipay.com"),
        entity_type=CompanyEntityType.SUBSIDIARY,
        parent_company_id=ALIBABA_ID,
    ),
    _seed(
        "alibaba-cloud",
        "Alibaba Cloud",
        "Alibaba Cloud / 阿里云",
        zh=("阿里云",),
        en=("Aliyun",),
        domains=("aliyun.com", "alibabacloud.com"),
        entity_type=CompanyEntityType.SUBSIDIARY,
        parent_company_id=ALIBABA_ID,
    ),
    _seed(
        "cainiao",
        "Cainiao",
        "Cainiao / 菜鸟",
        zh=("菜鸟", "菜鸟网络"),
        domains=("cainiao.com",),
        entity_type=CompanyEntityType.SUBSIDIARY,
        parent_company_id=ALIBABA_ID,
    ),
    _seed(
        "ele-me",
        "Ele.me",
        "Ele.me / 饿了么",
        zh=("饿了么",),
        domains=("ele.me",),
        entity_type=CompanyEntityType.SUBSIDIARY,
        parent_company_id=ALIBABA_ID,
    ),
    _seed(
        "fliggy",
        "Fliggy",
        "Fliggy / 飞猪",
        zh=("飞猪",),
        domains=("fliggy.com",),
        entity_type=CompanyEntityType.BRAND,
        parent_company_id=ALIBABA_ID,
    ),
    _seed(
        "douyin",
        "Douyin",
        "Douyin / 抖音",
        zh=("抖音", "抖音集团"),
        domains=("douyin.com",),
        entity_type=CompanyEntityType.BRAND,
        parent_company_id=BYTEDANCE_ID,
    ),
    _seed(
        "feishu",
        "Feishu",
        "Feishu / 飞书",
        zh=("飞书",),
        en=("Lark",),
        domains=("feishu.cn",),
        entity_type=CompanyEntityType.BRAND,
        parent_company_id=BYTEDANCE_ID,
    ),
    _seed(
        "volcano-engine",
        "Volcano Engine",
        "Volcano Engine / 火山引擎",
        zh=("火山引擎",),
        domains=("volcengine.com",),
        entity_type=CompanyEntityType.BRAND,
        parent_company_id=BYTEDANCE_ID,
    ),
    _seed(
        "tencent-cloud",
        "Tencent Cloud",
        "Tencent Cloud / 腾讯云",
        zh=("腾讯云",),
        domains=("cloud.tencent.com",),
        entity_type=CompanyEntityType.BRAND,
        parent_company_id=TENCENT_ID,
    ),
    _seed(
        "tencent-music",
        "Tencent Music",
        "Tencent Music / 腾讯音乐",
        zh=("腾讯音乐",),
        en=("TME",),
        domains=("tencentmusic.com",),
        entity_type=CompanyEntityType.SUBSIDIARY,
        parent_company_id=TENCENT_ID,
    ),
    _seed(
        "jd-logistics",
        "JD Logistics",
        "JD Logistics / 京东物流",
        zh=("京东物流",),
        domains=("jdl.com",),
        entity_type=CompanyEntityType.SUBSIDIARY,
        parent_company_id=JD_ID,
    ),
    _seed(
        "jd-technology",
        "JD Technology",
        "JD Technology / 京东科技",
        zh=("京东科技", "京东数科"),
        entity_type=CompanyEntityType.SUBSIDIARY,
        parent_company_id=JD_ID,
    ),
    _seed(
        "qunar",
        "Qunar",
        "Qunar / 去哪儿",
        zh=("去哪儿", "去哪儿网"),
        domains=("qunar.com",),
        entity_type=CompanyEntityType.SUBSIDIARY,
        parent_company_id=TRIP_COM_ID,
    ),
    _seed(
        "youdao",
        "Youdao",
        "Youdao / 网易有道",
        zh=("有道", "网易有道"),
        domains=("youdao.com",),
        entity_type=CompanyEntityType.SUBSIDIARY,
        parent_company_id=NETEASE_ID,
    ),
    # --- Social, content, and entertainment platforms.
    _seed(
        "weibo",
        "Weibo",
        "Weibo / 微博",
        zh=("微博", "新浪微博"),
        domains=("weibo.com",),
    ),
    _seed("sina", "Sina", "Sina / 新浪", zh=("新浪",), domains=("sina.com.cn",)),
    _seed("sohu", "Sohu", "Sohu / 搜狐", zh=("搜狐",), domains=("sohu.com",)),
    _seed("zhihu", "Zhihu", "Zhihu / 知乎", zh=("知乎",), domains=("zhihu.com",)),
    _seed(
        "xiaohongshu",
        "Xiaohongshu",
        "Xiaohongshu / 小红书",
        zh=("小红书",),
        en=("REDnote",),
        domains=("xiaohongshu.com",),
    ),
    _seed(
        "bilibili",
        "Bilibili",
        "Bilibili / 哔哩哔哩",
        zh=("哔哩哔哩", "B站"),
        domains=("bilibili.com",),
    ),
    _seed("iqiyi", "iQIYI", "iQIYI / 爱奇艺", zh=("爱奇艺",), domains=("iqiyi.com",)),
    _seed(
        "mango-tv",
        "Mango TV",
        "Mango TV / 芒果TV",
        zh=("芒果TV", "芒果超媒"),
        domains=("mgtv.com",),
    ),
    _seed(
        "ximalaya",
        "Ximalaya",
        "Ximalaya / 喜马拉雅",
        zh=("喜马拉雅",),
        domains=("ximalaya.com",),
    ),
    _seed("douyu", "Douyu", "Douyu / 斗鱼", zh=("斗鱼",), domains=("douyu.com",)),
    _seed("huya", "Huya", "Huya / 虎牙", zh=("虎牙",), domains=("huya.com",)),
    _seed(
        "joyy",
        "JOYY",
        "JOYY / 欢聚集团",
        zh=("欢聚集团",),
        en=("YY",),
        domains=("joyy.com",),
    ),
    _seed(
        "momo",
        "Momo",
        "Momo / 陌陌",
        zh=("陌陌", "挚文集团"),
        domains=("immomo.com",),
    ),
    # --- E-commerce and retail platforms.
    _seed(
        "pinduoduo",
        "Pinduoduo",
        "Pinduoduo / 拼多多",
        zh=("拼多多",),
        en=("PDD Holdings", "Temu"),
        domains=("pinduoduo.com",),
    ),
    _seed("vipshop", "Vipshop", "Vipshop / 唯品会", zh=("唯品会",), domains=("vip.com",)),
    _seed(
        "suning",
        "Suning",
        "Suning / 苏宁易购",
        zh=("苏宁", "苏宁易购"),
        domains=("suning.com",),
    ),
    # --- Classifieds and vertical platforms.
    _seed("58-com", "58.com", "58.com / 58同城", zh=("58同城",), domains=("58.com",)),
    _seed(
        "ke-holdings",
        "KE Holdings",
        "KE Holdings / 贝壳",
        zh=("贝壳", "贝壳找房", "链家"),
        domains=("ke.com",),
    ),
    _seed(
        "autohome",
        "Autohome",
        "Autohome / 汽车之家",
        zh=("汽车之家",),
        domains=("autohome.com.cn",),
    ),
    _seed("yiche", "Yiche", "Yiche / 易车", zh=("易车",), domains=("yiche.com",)),
    _seed(
        "kanzhun",
        "Kanzhun",
        "Kanzhun / BOSS直聘",
        zh=("BOSS直聘", "看准网"),
        domains=("zhipin.com",),
    ),
    _seed("liepin", "Liepin", "Liepin / 猎聘", zh=("猎聘",), domains=("liepin.com",)),
    _seed(
        "zhaopin",
        "Zhaopin",
        "Zhaopin / 智联招聘",
        zh=("智联招聘", "智联"),
        domains=("zhaopin.com",),
    ),
    _seed("51job", "51job", "51job / 前程无忧", zh=("前程无忧",), domains=("51job.com",)),
    # --- Travel and local services.
    _seed(
        "tongcheng-travel",
        "Tongcheng Travel",
        "Tongcheng Travel / 同程旅行",
        zh=("同程", "同程旅行"),
        domains=("ly.com",),
    ),
    # --- Mobility, EV, and autonomous driving.
    _seed(
        "hello-inc",
        "Hello Inc.",
        "Hello Inc. / 哈啰",
        zh=("哈啰", "哈啰出行"),
        domains=("hellobike.com",),
    ),
    _seed("nio", "NIO", "NIO / 蔚来", zh=("蔚来",), domains=("nio.com",)),
    _seed(
        "xpeng",
        "XPeng",
        "XPeng / 小鹏汽车",
        zh=("小鹏", "小鹏汽车"),
        domains=("xiaopeng.com",),
    ),
    _seed(
        "li-auto",
        "Li Auto",
        "Li Auto / 理想汽车",
        zh=("理想汽车", "理想"),
        domains=("lixiang.com",),
    ),
    _seed(
        "horizon-robotics",
        "Horizon Robotics",
        "Horizon Robotics / 地平线",
        zh=("地平线",),
        domains=("horizon.auto",),
    ),
    _seed(
        "pony-ai",
        "Pony.ai",
        "Pony.ai / 小马智行",
        zh=("小马智行",),
        domains=("pony.ai",),
    ),
    _seed(
        "weride",
        "WeRide",
        "WeRide / 文远知行",
        zh=("文远知行",),
        domains=("weride.ai",),
    ),
    _seed("momenta", "Momenta", "Momenta", domains=("momenta.ai",)),
    # --- Fintech.
    _seed("lufax", "Lufax", "Lufax / 陆金所", zh=("陆金所",), domains=("lu.com",)),
    _seed(
        "du-xiaoman",
        "Du Xiaoman",
        "Du Xiaoman / 度小满",
        zh=("度小满", "度小满金融"),
        domains=("duxiaoman.com",),
    ),
    _seed("webank", "WeBank", "WeBank / 微众银行", zh=("微众银行",), domains=("webank.com",)),
    _seed(
        "east-money",
        "East Money",
        "East Money / 东方财富",
        zh=("东方财富",),
        domains=("eastmoney.com",),
    ),
    _seed("futu", "Futu", "Futu / 富途", zh=("富途", "富途证券"), domains=("futunn.com",)),
    # --- Security, cloud, and enterprise software.
    _seed(
        "qihoo-360",
        "Qihoo 360",
        "Qihoo 360 / 三六零",
        zh=("三六零", "奇虎360", "360集团"),
        domains=("360.cn",),
    ),
    _seed(
        "kingsoft",
        "Kingsoft",
        "Kingsoft / 金山软件",
        zh=("金山软件",),
        domains=("kingsoft.com",),
    ),
    _seed(
        "kingsoft-office",
        "Kingsoft Office",
        "Kingsoft Office / 金山办公",
        zh=("金山办公",),
        en=("WPS",),
        domains=("wps.cn",),
    ),
    _seed(
        "kingsoft-cloud",
        "Kingsoft Cloud",
        "Kingsoft Cloud / 金山云",
        zh=("金山云",),
        domains=("ksyun.com",),
    ),
    _seed(
        "qi-an-xin",
        "Qi An Xin",
        "Qi An Xin / 奇安信",
        zh=("奇安信",),
        domains=("qianxin.com",),
    ),
    _seed(
        "sangfor",
        "Sangfor",
        "Sangfor / 深信服",
        zh=("深信服",),
        domains=("sangfor.com.cn",),
    ),
    # --- AI platforms and research labs.
    _seed(
        "iflytek",
        "iFlytek",
        "iFlytek / 科大讯飞",
        zh=("科大讯飞", "讯飞"),
        domains=("iflytek.com",),
    ),
    _seed(
        "sensetime",
        "SenseTime",
        "SenseTime / 商汤科技",
        zh=("商汤", "商汤科技"),
        domains=("sensetime.com",),
    ),
    _seed(
        "megvii",
        "Megvii",
        "Megvii / 旷视科技",
        zh=("旷视", "旷视科技"),
        domains=("megvii.com",),
    ),
    _seed(
        "zhipu-ai",
        "Zhipu AI",
        "Zhipu AI / 智谱",
        zh=("智谱", "智谱AI"),
        domains=("zhipuai.cn",),
    ),
    _seed(
        "moonshot-ai",
        "Moonshot AI",
        "Moonshot AI / 月之暗面",
        zh=("月之暗面",),
        en=("Kimi",),
        domains=("moonshot.cn",),
    ),
    _seed("minimax", "MiniMax", "MiniMax", zh=("稀宇科技",), domains=("minimaxi.com",)),
    _seed(
        "deepseek",
        "DeepSeek",
        "DeepSeek / 深度求索",
        zh=("深度求索",),
        domains=("deepseek.com",),
    ),
    _seed(
        "baichuan-ai",
        "Baichuan AI",
        "Baichuan AI / 百川智能",
        zh=("百川智能",),
        domains=("baichuan-ai.com",),
    ),
    _seed("01-ai", "01.AI", "01.AI / 零一万物", zh=("零一万物",), domains=("01.ai",)),
    _seed(
        "stepfun",
        "StepFun",
        "StepFun / 阶跃星辰",
        zh=("阶跃星辰",),
        domains=("stepfun.com",),
    ),
    # --- Consumer hardware with large software organizations.
    _seed("oppo", "OPPO", "OPPO", domains=("oppo.com",)),
    _seed("vivo", "vivo", "vivo", domains=("vivo.com",)),
    _seed("honor", "Honor", "Honor / 荣耀", zh=("荣耀",), domains=("hihonor.com",)),
    _seed("lenovo", "Lenovo", "Lenovo / 联想", zh=("联想",), domains=("lenovo.com",)),
    _seed("dji", "DJI", "DJI / 大疆", zh=("大疆", "大疆创新"), domains=("dji.com",)),
    _seed(
        "insta360",
        "Insta360",
        "Insta360 / 影石",
        zh=("影石",),
        domains=("insta360.com",),
    ),
    # --- Game studios and publishers.
    _seed(
        "mihoyo",
        "miHoYo",
        "miHoYo / 米哈游",
        zh=("米哈游",),
        en=("HoYoverse",),
        domains=("mihoyo.com",),
    ),
    _seed(
        "lilith-games",
        "Lilith Games",
        "Lilith Games / 莉莉丝",
        zh=("莉莉丝",),
        domains=("lilith.com",),
    ),
    _seed(
        "papergames",
        "Papergames",
        "Papergames / 叠纸",
        zh=("叠纸游戏", "叠纸网络"),
        domains=("papegames.cn",),
    ),
    _seed(
        "game-science",
        "Game Science",
        "Game Science / 游戏科学",
        zh=("游戏科学",),
        domains=("gamesci.com.cn",),
    ),
    _seed(
        "perfect-world",
        "Perfect World",
        "Perfect World / 完美世界",
        zh=("完美世界",),
        domains=("wanmei.com",),
    ),
    _seed(
        "37-interactive",
        "37 Interactive Entertainment",
        "37 Interactive / 三七互娱",
        zh=("三七互娱",),
        domains=("37.com",),
    ),
    _seed(
        "hypergryph",
        "Hypergryph",
        "Hypergryph / 鹰角网络",
        zh=("鹰角网络", "鹰角"),
        domains=("hypergryph.com",),
    ),
    # --- Logistics.
    _seed(
        "sf-express",
        "SF Express",
        "SF Express / 顺丰",
        zh=("顺丰", "顺丰速运"),
        domains=("sf-express.com",),
    ),
    _seed(
        "zto-express",
        "ZTO Express",
        "ZTO Express / 中通快递",
        zh=("中通", "中通快递"),
        domains=("zto.com",),
    ),
    # --- Education technology.
    _seed(
        "tal-education",
        "TAL Education",
        "TAL Education / 好未来",
        zh=("好未来", "学而思"),
        domains=("100tal.com",),
    ),
    _seed(
        "new-oriental",
        "New Oriental",
        "New Oriental / 新东方",
        zh=("新东方",),
        domains=("xdf.cn",),
    ),
    _seed(
        "yuanfudao",
        "Yuanfudao",
        "Yuanfudao / 猿辅导",
        zh=("猿辅导",),
        domains=("yuanfudao.com",),
    ),
    _seed(
        "zuoyebang",
        "Zuoyebang",
        "Zuoyebang / 作业帮",
        zh=("作业帮",),
        domains=("zuoyebang.com",),
    ),
)


COMMON_COMPANY_SEEDS: tuple[CompanySeed, ...] = (
    *_FOUNDATION_COMPANY_SEEDS,
    *CHINA_INTERNET_MAJOR_SEEDS,
)
