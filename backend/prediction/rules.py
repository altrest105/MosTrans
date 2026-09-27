def classify_risk(deviation_s: float) -> str:
    """Преобразовать модуль отклонения от графика в уровень риска.

    Положительное значение означает опоздание, отрицательное — опережение.
    Оба направления считаются нарушением графика, поэтому риск определяется
    по абсолютной величине отклонения.
    """

    absolute_deviation_s = abs(float(deviation_s))

    if absolute_deviation_s > 120:
        return "red"
    if absolute_deviation_s > 60:
        return "yellow"
    return "green"


def deviation_direction(deviation_s: float) -> str:
    """Получить направление отклонения от расписания."""

    if deviation_s > 0:
        return "late"
    if deviation_s < 0:
        return "early"
    return "on_time"


def explain_prediction(
    deviation_s: float,
    features: dict[str, float | None],
) -> tuple[str, str]:
    """Получить объяснимую причину и рекомендацию без отдельной ML-модели."""

    telemetry_age = features.get("telemetry_age_s")
    stopped_share = features.get("stopped_share_10m")
    mean_speed = features.get("mean_speed_10m")
    last_speed = features.get("last_speed")
    cur_dev = features.get("cur_dev_s")

    if telemetry_age is not None and telemetry_age > 30:
        return (
            "Нестабильная телеметрия",
            "Проверить канал связи с бортовым терминалом и использовать последнее известное состояние.",
        )

    # Опережение графика — самостоятельный тип инцидента. Не называем его
    # «отрицательной задержкой»: оператору важен факт слишком раннего движения.
    if deviation_s < -60:
        if cur_dev is not None and cur_dev < -120:
            return (
                "Накопленное опережение графика",
                "Предупредить водителя о необходимости соблюдать график движения и не прибывать раньше планового времени.",
            )

        if (
            mean_speed is not None
            and last_speed is not None
            and mean_speed >= 20
            and last_speed >= mean_speed
        ):
            return (
                "Движение быстрее планового темпа",
                "Предупредить водителя об опережении и необходимости соблюдать график движения.",
            )

        return (
            "Опережение графика",
            "Предупредить водителя о необходимости соблюдать график движения и усилить контроль следующих участков.",
        )

    if stopped_share is not None and stopped_share >= 0.5:
        return (
            "Длительный простой",
            "Связаться с водителем и уточнить причину остановки.",
        )

    if (
        mean_speed is not None
        and last_speed is not None
        and mean_speed <= 8
        and last_speed <= 8
    ):
        return (
            "Снижение средней скорости",
            "Связаться с водителем и уточнить дорожную обстановку.",
        )

    if cur_dev is not None and cur_dev > 120:
        return (
            "Накопленное отставание от графика",
            "Предупредить водителя об отклонении и усилить контроль следующих участков.",
        )

    if deviation_s > 120:
        return (
            "Высокий риск опоздания по динамике движения",
            "Связаться с водителем; при подтверждении проблемы рассмотреть диспетчерское регулирование.",
        )

    if deviation_s > 60:
        return (
            "Формируется отставание от графика",
            "Усилить контроль ТС и при ухудшении связаться с водителем.",
        )

    return (
        "Существенных признаков отклонения не выявлено",
        "Продолжать мониторинг в штатном режиме.",
    )
